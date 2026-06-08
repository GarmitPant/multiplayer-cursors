"""
FastAPI glue: WebSocket endpoint, local socket registry, lifespan wiring.

Per-room RoomCache + fixed-tick batched socket fan-out (backplane ingests,
ticker drains). Redis carries raw deltas unchanged.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .backplane import Backplane
from .config import settings
from .identity import EphemeralIdentityProvider
from . import protocol
from .rooms import RoomCache
from . import ticker

logger = logging.getLogger("cursor")

# local-to-this-replica registry: room_id -> {websocket: identity}
rooms: dict[str, dict[WebSocket, dict]] = {}
caches: dict[str, RoomCache] = {}
# one Redis subscriber task per active room on this replica
room_tasks: dict[str, asyncio.Task] = {}

backplane = Backplane(settings.redis_url)
identity_provider = EphemeralIdentityProvider()


async def _evict_same_user(room_id: str, user_id: str, keep: WebSocket) -> None:
    """Drop any other local socket registered under the same user_id (reconnect replace)."""
    room = rooms.get(room_id)
    if not room:
        return
    for old_ws, ident in list(room.items()):
        if old_ws is not keep and ident.get("user_id") == user_id:
            room.pop(old_ws, None)
            try:
                await old_ws.close()
            except Exception:
                logger.warning(
                    "failed closing evicted socket room=%s user=%s",
                    room_id,
                    user_id,
                    exc_info=True,
                )


def _ingest(room_id: str, parsed: dict) -> None:
    cache = caches.get(room_id)
    if cache is None:
        return
    cache.ingest(parsed)


async def flush_fn(room_id: str, msg: dict) -> None:
    data = json.dumps(msg)
    for ws in list(rooms.get(room_id, {})):
        try:
            await ws.send_text(data)
        except Exception:
            logger.warning("dropping dead socket in room %s", room_id, exc_info=True)
            rooms.get(room_id, {}).pop(ws, None)


async def relay_room(room_id: str) -> None:
    await backplane.subscribe_room(room_id, lambda parsed: _ingest(room_id, parsed))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logger.info("app startup replica=%s", settings.replica_id)
    await backplane.connect()
    logger.info("redis connected url=%s", settings.redis_url.split("@")[-1])
    tick_state = {"tick_ms": settings.tick_ms}
    app.state.tick_state = tick_state
    app.state.ticker_task = asyncio.create_task(
        ticker.run_ticker(tick_state, caches, flush_fn)
    )
    logger.info("ticker started tick_ms=%d", settings.tick_ms)
    yield
    logger.info("app shutdown")
    app.state.ticker_task.cancel()
    try:
        await app.state.ticker_task
    except asyncio.CancelledError:
        pass
    logger.info("ticker stopped")
    await backplane.close()
    logger.info("redis disconnected")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    try:
        await backplane.ping()
        return {"ok": True, "redis": "up", "replica": settings.replica_id}
    except Exception:
        logger.error("healthz: redis ping failed", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "redis": "down", "replica": settings.replica_id},
        )


@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str):
    if len(room_id) > settings.max_room_id_len:
        logger.warning("rejecting ws: room_id too long len=%d", len(room_id))
        await ws.accept()
        await ws.close(code=1008, reason="room_id too long")
        return

    await ws.accept()

    if len(rooms.get(room_id, {})) >= settings.max_room_connections:
        logger.warning(
            "rejecting ws: room %s at connection cap (%d)",
            room_id,
            settings.max_room_connections,
        )
        await ws.close(code=1008, reason="room full")
        return

    params = ws.query_params
    identity = identity_provider.create(
        params.get("name"),
        user_id=params.get("user_id"),
        color=params.get("color"),
    )

    if room_id not in caches:
        caches[room_id] = RoomCache()
        logger.info("room created room=%s", room_id)
    await _evict_same_user(room_id, identity["user_id"], ws)
    rooms.setdefault(room_id, {})[ws] = identity
    if room_id not in room_tasks or room_tasks[room_id].done():
        room_tasks[room_id] = asyncio.create_task(relay_room(room_id))

    logger.info("client connected room=%s user=%s", room_id, identity["user_id"])

    # init snapshot: self + peers known to THIS replica.
    # (Full cross-replica snapshot would need a Redis presence set.)
    peers = [v for w, v in rooms[room_id].items() if w is not ws]
    await ws.send_text(json.dumps({
        "type": "init", "self": identity, "peers": peers,
        "replica": settings.replica_id,
        "tick_ms": app.state.tick_state["tick_ms"],
        "default_tick_ms": settings.tick_ms,
    }))
    try:
        await backplane.publish(room_id, {"type": "peer_joined", **identity})
    except Exception:
        logger.error(
            "peer_joined publish failed room=%s user=%s",
            room_id,
            identity["user_id"],
            exc_info=True,
        )

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            try:
                model = protocol.parse_inbound(msg)
            except ValidationError:
                continue
            if model is None:
                continue
            if model.type == "heartbeat":
                continue
            if model.type == "set_tick_ms":
                app.state.tick_state["tick_ms"] = model.value
                logger.info(
                    "tick_ms changed to %d by %s",
                    model.value,
                    identity["user_id"],
                )
                # Per-room broadcast so inspector sliders stay in sync. The ticker
                # loop is one task per replica (all rooms); users in other rooms
                # on this replica feel the new interval but their slider won't update.
                try:
                    await backplane.publish(
                        room_id, {"type": "tick_ms", "value": model.value},
                    )
                except Exception:
                    logger.error(
                        "tick_ms broadcast failed room=%s user=%s",
                        room_id,
                        identity["user_id"],
                        exc_info=True,
                    )
                continue
            out = model.model_dump(exclude_none=True)
            out["user_id"] = identity["user_id"]
            try:
                await backplane.publish(room_id, out)
            except Exception:
                logger.error(
                    "publish failed room=%s user=%s type=%s",
                    room_id,
                    identity["user_id"],
                    out.get("type"),
                    exc_info=True,
                )
    except WebSocketDisconnect:
        pass
    finally:
        rooms.get(room_id, {}).pop(ws, None)
        logger.info("client disconnected room=%s user=%s", room_id, identity["user_id"])
        try:
            await backplane.publish(room_id, {"type": "peer_left", "user_id": identity["user_id"]})
        except Exception:
            logger.error(
                "peer_left publish failed room=%s user=%s",
                room_id,
                identity["user_id"],
                exc_info=True,
            )
        if room_id in rooms and not rooms[room_id]:
            rooms.pop(room_id, None)
            caches.pop(room_id, None)
            task = room_tasks.pop(room_id, None)
            if task:
                task.cancel()
            logger.info("room torn down room=%s", room_id)

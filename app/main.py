"""
FastAPI glue: WebSocket endpoint, local socket registry, lifespan wiring.

Pick 2: per-room RoomCache + fixed-tick batched socket fan-out (backplane ingests,
ticker drains). Redis still carries raw deltas unchanged.
"""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .backplane import Backplane
from .config import settings
from .identity import EphemeralIdentityProvider
from . import protocol
from .rooms import RoomCache
from . import ticker

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
                pass


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
            rooms.get(room_id, {}).pop(ws, None)


async def relay_room(room_id: str) -> None:
    await backplane.subscribe_room(room_id, lambda parsed: _ingest(room_id, parsed))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await backplane.connect()
    app.state.ticker_task = asyncio.create_task(
        ticker.run_ticker(settings.tick_ms, caches, flush_fn)
    )
    yield
    app.state.ticker_task.cancel()
    try:
        await app.state.ticker_task
    except asyncio.CancelledError:
        pass
    await backplane.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "replica": settings.replica_id}


@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str):
    await ws.accept()
    params = ws.query_params
    identity = identity_provider.create(
        params.get("name"),
        user_id=params.get("user_id"),
        color=params.get("color"),
    )

    if room_id not in caches:
        caches[room_id] = RoomCache()
    await _evict_same_user(room_id, identity["user_id"], ws)
    rooms.setdefault(room_id, {})[ws] = identity
    if room_id not in room_tasks or room_tasks[room_id].done():
        room_tasks[room_id] = asyncio.create_task(relay_room(room_id))

    # init snapshot: self + peers known to THIS replica.
    # (Full cross-replica snapshot needs a Redis presence set — LLD phase.)
    peers = [v for w, v in rooms[room_id].items() if w is not ws]
    await ws.send_text(json.dumps({
        "type": "init", "self": identity, "peers": peers,
        "replica": settings.replica_id,
    }))
    await backplane.publish(room_id, {"type": "peer_joined", **identity})

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
            out = model.model_dump(exclude_none=True)
            out["user_id"] = identity["user_id"]
            await backplane.publish(room_id, out)
    except WebSocketDisconnect:
        pass
    finally:
        rooms.get(room_id, {}).pop(ws, None)
        await backplane.publish(room_id, {"type": "peer_left", "user_id": identity["user_id"]})
        if room_id in rooms and not rooms[room_id]:
            rooms.pop(room_id, None)
            caches.pop(room_id, None)
            task = room_tasks.pop(room_id, None)
            if task:
                task.cancel()

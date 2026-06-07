"""
Thin vertical slice. Proves the pipes: WebSocket + ephemeral identity +
Redis pub/sub fan-out (cross-replica) + basic join/leave presence.

Pick 2: per-room RoomCache + fixed-tick batched socket fan-out (relay ingests,
ticker drains). Redis still carries raw deltas unchanged.
"""
import asyncio
import json
import random
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .config import settings
from . import protocol
from .rooms import RoomCache
from . import ticker

COLORS = ["#4a9eed", "#22c55e", "#f59e0b", "#ef4444",
          "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]

# local-to-this-replica registry: room_id -> {websocket: identity}
rooms: dict[str, dict[WebSocket, dict]] = {}
caches: dict[str, RoomCache] = {}
# one Redis subscriber task per active room on this replica
room_tasks: dict[str, asyncio.Task] = {}
r: redis.Redis


def chan(room_id: str) -> str:
    return f"room:{room_id}"


async def flush_fn(room_id: str, msg: dict) -> None:
    data = json.dumps(msg)
    for ws in list(rooms.get(room_id, {})):
        try:
            await ws.send_text(data)
        except Exception:
            rooms.get(room_id, {}).pop(ws, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global r
    r = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.ticker_task = asyncio.create_task(
        ticker.run_ticker(settings.tick_ms, caches, flush_fn)
    )
    yield
    app.state.ticker_task.cancel()
    try:
        await app.state.ticker_task
    except asyncio.CancelledError:
        pass
    await r.aclose()


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


async def publish(room_id: str, payload: dict) -> None:
    await r.publish(chan(room_id), json.dumps(payload))


async def relay_room(room_id: str) -> None:
    """Ingest Redis channel messages into the per-room coalescing cache."""
    pubsub = r.pubsub()
    await pubsub.subscribe(chan(room_id))
    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            cache = caches.get(room_id)
            if cache is None:
                continue
            try:
                parsed = json.loads(msg["data"])
            except json.JSONDecodeError:
                continue
            cache.ingest(parsed)
    finally:
        await pubsub.unsubscribe(chan(room_id))
        await pubsub.aclose()


@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str):
    await ws.accept()
    identity = {
        "user_id": "u_" + uuid.uuid4().hex[:8],
        "name": ws.query_params.get("name") or f"user-{uuid.uuid4().hex[:4]}",
        "color": random.choice(COLORS),
    }

    if room_id not in caches:
        caches[room_id] = RoomCache()
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
    await publish(room_id, {"type": "peer_joined", **identity})

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
            await publish(room_id, out)
    except WebSocketDisconnect:
        pass
    finally:
        rooms.get(room_id, {}).pop(ws, None)
        await publish(room_id, {"type": "peer_left", "user_id": identity["user_id"]})
        if room_id in rooms and not rooms[room_id]:
            rooms.pop(room_id, None)
            caches.pop(room_id, None)
            task = room_tasks.pop(room_id, None)
            if task:
                task.cancel()

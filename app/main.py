"""
Thin vertical slice. Proves the pipes: WebSocket + ephemeral identity +
Redis pub/sub fan-out (cross-replica) + basic join/leave presence.

NOT in this file (LLD phase): per-tick batching/coalescing, presence TTL,
cross-replica snapshot, reconnect handling, draw-trail semantics.
"""
import asyncio
import json
import random
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

COLORS = ["#4a9eed", "#22c55e", "#f59e0b", "#ef4444",
          "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]

# local-to-this-replica registry: room_id -> {websocket: identity}
rooms: dict[str, dict[WebSocket, dict]] = {}
# one Redis subscriber task per active room on this replica
room_tasks: dict[str, asyncio.Task] = {}
r: redis.Redis


def chan(room_id: str) -> str:
    return f"room:{room_id}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global r
    r = redis.from_url(settings.redis_url, decode_responses=True)
    yield
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
    """Relay every message on the room's Redis channel to local sockets."""
    pubsub = r.pubsub()
    await pubsub.subscribe(chan(room_id))
    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            data = msg["data"]
            for ws in list(rooms.get(room_id, {})):
                try:
                    await ws.send_text(data)
                except Exception:
                    rooms.get(room_id, {}).pop(ws, None)
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
            # THIN SLICE: naive immediate relay. No batching/coalescing here.
            if msg.get("type") in ("cursor", "draw", "cursor_leave"):
                msg["user_id"] = identity["user_id"]
                await publish(room_id, msg)
            # "heartbeat" intentionally ignored in the slice.
    except WebSocketDisconnect:
        pass
    finally:
        rooms.get(room_id, {}).pop(ws, None)
        await publish(room_id, {"type": "peer_left", "user_id": identity["user_id"]})
        if room_id in rooms and not rooms[room_id]:
            rooms.pop(room_id, None)
            task = room_tasks.pop(room_id, None)
            if task:
                task.cancel()

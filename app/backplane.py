"""Redis pub/sub transport — publish raw deltas, subscribe per room."""
from __future__ import annotations

import json
from collections.abc import Callable

import redis.asyncio as redis


def chan(room_id: str) -> str:
    return f"room:{room_id}"


class Backplane:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._r: redis.Redis | None = None

    async def connect(self) -> None:
        self._r = redis.from_url(self._redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._r is not None:
            await self._r.aclose()
            self._r = None

    async def publish(self, room_id: str, payload: dict) -> None:
        await self._r.publish(chan(room_id), json.dumps(payload))

    async def subscribe_room(
        self,
        room_id: str,
        on_message: Callable[[dict], None],
    ) -> None:
        """Run the per-room relay loop; calls on_message(parsed_dict) for each delta."""
        pubsub = self._r.pubsub()
        await pubsub.subscribe(chan(room_id))
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    parsed = json.loads(msg["data"])
                except json.JSONDecodeError:
                    continue
                on_message(parsed)
        finally:
            await pubsub.unsubscribe(chan(room_id))
            await pubsub.aclose()

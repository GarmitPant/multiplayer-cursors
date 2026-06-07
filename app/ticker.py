"""Fixed-tick flush loop for Pick 2 batched fan-out."""
import asyncio


async def run_ticker(tick_ms: int, caches: dict, flush_fn) -> None:
    """Every tick_ms: drain each non-empty RoomCache and flush its batched
    messages to local sockets via flush_fn(room_id, message)."""
    interval = tick_ms / 1000
    while True:
        await asyncio.sleep(interval)
        for room_id, cache in list(caches.items()):     # list() tolerates concurrent room teardown
            if cache.empty():
                continue
            for msg in cache.drain():
                await flush_fn(room_id, msg)

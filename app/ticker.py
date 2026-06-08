"""Fixed-tick flush loop for Pick 2 batched fan-out."""
import asyncio


async def run_ticker(tick_state: dict, caches: dict, flush_fn) -> None:
    """Every tick_ms: drain each non-empty RoomCache and flush its batched
    messages to local sockets via flush_fn(room_id, message).

    tick_state is a mutable {"tick_ms": int} ref; the loop re-reads it each
    iteration so dev set_tick_ms can change the interval at runtime."""
    while True:
        interval = tick_state["tick_ms"] / 1000
        await asyncio.sleep(interval)
        for room_id, cache in list(caches.items()):     # list() tolerates concurrent room teardown
            if cache.empty():
                continue
            for msg in cache.drain():
                await flush_fn(room_id, msg)

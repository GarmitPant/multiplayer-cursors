"""Unit tests for the fixed-tick flush loop."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app import ticker
from app.rooms import RoomCache


@pytest.mark.asyncio
async def test_run_ticker_drains_non_empty_cache():
    cache = RoomCache()
    cache.ingest({"type": "cursor", "user_id": "u1", "p": [0.1, 0.1], "v": [0, 0], "t": 1})
    caches = {"room-a": cache}
    flush = AsyncMock()
    tick_state = {"tick_ms": 20}
    task = asyncio.create_task(ticker.run_ticker(tick_state, caches, flush))
    await asyncio.sleep(0.06)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert flush.await_count >= 1
    args = flush.await_args_list[0].args
    assert args[0] == "room-a"
    assert args[1]["type"] == "cursors"


@pytest.mark.asyncio
async def test_run_ticker_skips_empty_cache():
    caches = {"empty-room": RoomCache()}
    flush = AsyncMock()
    tick_state = {"tick_ms": 20}
    task = asyncio.create_task(ticker.run_ticker(tick_state, caches, flush))
    await asyncio.sleep(0.06)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ticker_respects_runtime_tick_change():
    cache = RoomCache()
    cache.ingest({"type": "cursor", "user_id": "u1", "p": [0.2, 0.2], "v": [0, 0], "t": 1})
    caches = {"room-b": cache}
    flush = AsyncMock()
    tick_state = {"tick_ms": 80}
    task = asyncio.create_task(ticker.run_ticker(tick_state, caches, flush))
    tick_state["tick_ms"] = 15
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert flush.await_count >= 1

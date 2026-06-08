"""Unit tests for Redis backplane transport."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.backplane import Backplane, chan


@pytest.mark.asyncio
async def test_ping_raises_when_not_connected():
    bp = Backplane("redis://fake")
    with pytest.raises(ConnectionError, match="not connected"):
        await bp.ping()


@pytest.mark.asyncio
async def test_connect_close_and_ping(fake_redis_backend):
    bp = Backplane("redis://fake")
    await bp.connect()
    await bp.ping()
    await bp.close()
    assert bp._r is None


@pytest.mark.asyncio
async def test_publish_and_subscribe_delivers_payload(fake_redis_backend):
    bp = Backplane("redis://fake")
    await bp.connect()
    received: list[dict] = []

    async def listen():
        await bp.subscribe_room("demo", received.append)

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.02)
    await bp.publish("demo", {"type": "cursor", "user_id": "u1", "p": [0.1, 0.2], "v": [0, 0], "t": 1})
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(received) == 1
    assert received[0]["type"] == "cursor"
    assert received[0]["user_id"] == "u1"


@pytest.mark.asyncio
async def test_subscribe_drops_non_json(fake_redis_backend, caplog):
    bp = Backplane("redis://fake")
    await bp.connect()
    received: list[dict] = []

    async def listen():
        await bp.subscribe_room("bad-json", received.append)

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.02)
    await fake_redis_backend.publish(chan("bad-json"), "not-json")
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert received == []
    assert any("dropping non-JSON" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_publish_logs_and_reraises(fake_redis_backend, caplog):
    bp = Backplane("redis://fake")
    await bp.connect()
    with patch.object(bp._r, "publish", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError, match="boom"):
            await bp.publish("x", {"type": "cursor"})
    assert any("redis publish failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_subscribe_unsubscribes_on_cancel(fake_redis_backend):
    bp = Backplane("redis://fake")
    await bp.connect()

    async def listen():
        await bp.subscribe_room("tear", lambda _m: None)

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_subscribe_handler_error_propagates(fake_redis_backend, caplog):
    bp = Backplane("redis://fake")
    await bp.connect()

    def boom(_msg):
        raise ValueError("handler failed")

    async def listen():
        await bp.subscribe_room("boom", boom)

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.02)
    await bp.publish("boom", {"type": "peer_joined", "user_id": "u_x"})
    with pytest.raises(ValueError, match="handler failed"):
        await task
    assert any("subscribe loop failed" in r.message for r in caplog.records)

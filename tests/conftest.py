"""Shared pytest fixtures — in-memory Redis, isolated replica state."""
from __future__ import annotations

import sys
from pathlib import Path

import fakeredis.aioredis
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


@pytest.fixture(autouse=True)
def isolate_replica_state():
    """Reset module-level room registry between tests."""
    import app.main as main

    for task in list(main.room_tasks.values()):
        if not task.done():
            task.cancel()
    main.rooms.clear()
    main.caches.clear()
    main.room_tasks.clear()
    main.backplane._r = None
    yield
    for task in list(main.room_tasks.values()):
        if not task.done():
            task.cancel()
    main.rooms.clear()
    main.caches.clear()
    main.room_tasks.clear()
    main.backplane._r = None


@pytest.fixture(autouse=True)
def fake_redis_backend(monkeypatch):
    """Use fakeredis instead of a live Redis (CI, local, Render build — no REDIS_URL needed)."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def fake_from_url(url, **kwargs):
        return fake

    monkeypatch.setattr("app.backplane.redis.from_url", fake_from_url)
    return fake


@pytest.fixture
def fast_tick(monkeypatch):
    """Short ticker interval so integration tests finish quickly."""
    import app.main as main

    monkeypatch.setattr(main.settings, "tick_ms", 20)
    return 20

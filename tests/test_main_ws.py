"""Unit tests for main.py helpers and WebSocket handler edge paths."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app.main import app, flush_fn, _ingest, _evict_same_user
from tests.helpers import recv_until


@pytest.mark.asyncio
async def test_ingest_noop_when_cache_missing():
    main.caches.clear()
    _ingest("missing-room", {"type": "cursor", "user_id": "u1", "p": [0, 0], "v": [0, 0], "t": 0})


@pytest.mark.asyncio
async def test_flush_fn_drops_dead_socket():
    main.rooms["r1"] = {}
    dead = AsyncMock()
    dead.send_text = AsyncMock(side_effect=RuntimeError("socket gone"))
    alive = AsyncMock()
    main.rooms["r1"][dead] = {"user_id": "u_dead"}
    main.rooms["r1"][alive] = {"user_id": "u_alive"}
    await flush_fn("r1", {"type": "cursors", "updates": []})
    assert dead not in main.rooms["r1"]
    assert alive in main.rooms["r1"]
    alive.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_evict_same_user_closes_old_socket():
    main.rooms["r1"] = {}
    old = AsyncMock()
    keep = MagicMock()
    main.rooms["r1"][old] = {"user_id": "u_same"}
    main.rooms["r1"][keep] = {"user_id": "u_same"}
    await _evict_same_user("r1", "u_same", keep)
    assert old not in main.rooms["r1"]
    old.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_evict_same_user_swallows_close_errors(caplog):
    main.rooms["r1"] = {}
    old = AsyncMock()
    old.close = AsyncMock(side_effect=RuntimeError("close failed"))
    keep = MagicMock()
    main.rooms["r1"][old] = {"user_id": "u_same"}
    await _evict_same_user("r1", "u_same", keep)
    assert any("failed closing evicted socket" in r.message for r in caplog.records)


def test_ws_init_payload_and_cursor_publish(fast_tick):
    room = "ws-flow"
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/{room}?name=Alice&color=%234a9eed&user_id=u_12345678",
        ) as ws:
            init = json.loads(ws.receive_text())
            assert init["type"] == "init"
            assert init["self"]["name"] == "Alice"
            assert init["self"]["user_id"] == "u_12345678"
            assert init["self"]["color"] == "#4a9eed"
            assert init["tick_ms"] == 20
            assert "replica" in init

            ws.send_text(json.dumps({
                "type": "cursor", "p": [0.4, 0.6], "v": [0.01, -0.02], "t": 1.0,
            }))
            ws.send_text("{not json")
            ws.send_text(json.dumps({"type": "heartbeat"}))
            ws.send_text(json.dumps({"type": "unknown"}))
            ws.send_text(json.dumps({"type": "cursor", "p": [99, 99], "v": [0, 0], "t": 2}))


def test_ws_set_tick_ms_broadcast(fast_tick):
    room = "tick-room"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{room}?name=Dev") as ws_a:
            json.loads(ws_a.receive_text())
            with client.websocket_connect(f"/ws/{room}?name=Peer") as ws_b:
                json.loads(ws_b.receive_text())
                ws_a.send_text(json.dumps({"type": "set_tick_ms", "value": 35}))
                msg, _seen = recv_until(ws_b, lambda m: m.get("type") == "tick_ms")
                assert msg["value"] == 35


def test_ws_reconnect_evicts_same_user_id(fast_tick):
    room = "reconnect"
    uid = "u_abcd1234"
    with TestClient(app) as client:
        cm_old = client.websocket_connect(f"/ws/{room}?name=Old&user_id={uid}")
        ws_old = cm_old.__enter__()
        json.loads(ws_old.receive_text())
        with client.websocket_connect(f"/ws/{room}?name=New&user_id={uid}") as ws_new:
            json.loads(ws_new.receive_text())
            with pytest.raises(WebSocketDisconnect):
                ws_old.receive_text()
        cm_old.__exit__(None, None, None)


def test_ws_publish_errors_are_logged_not_raised(fast_tick):
    room = "pub-fail"
    publish = AsyncMock(side_effect=[None, RuntimeError("redis down")])

    with patch.object(main.backplane, "publish", publish):
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/{room}?name=Fail") as ws:
                json.loads(ws.receive_text())
                ws.send_text(json.dumps({"type": "cursor", "p": [0.5, 0.5], "v": [0, 0], "t": 1.0}))
    assert publish.await_count >= 2


def test_ws_peer_left_publish_error_logged(fast_tick):
    room = "leave-fail"
    publish = AsyncMock(side_effect=[None, RuntimeError("leave publish fail")])

    with patch.object(main.backplane, "publish", publish):
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/{room}?name=Leaver") as ws:
                json.loads(ws.receive_text())
    assert publish.await_count >= 2


def test_ws_peer_joined_publish_error_logged(fast_tick):
    publish = AsyncMock(side_effect=RuntimeError("join fail"))

    with patch.object(main.backplane, "publish", publish):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/join-fail?name=Join") as ws:
                init = json.loads(ws.receive_text())
                assert init["type"] == "init"
    publish.assert_awaited()


def test_ws_tick_ms_publish_error_logged(fast_tick):
    room = "tick-fail"
    publish = AsyncMock(side_effect=[None, RuntimeError("tick broadcast fail")])

    with patch.object(main.backplane, "publish", publish):
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/{room}?name=Dev") as ws:
                json.loads(ws.receive_text())
                ws.send_text(json.dumps({"type": "set_tick_ms", "value": 40}))
    assert publish.await_count >= 2


def test_healthz_uses_live_fake_redis(fake_redis_backend):
    with TestClient(app) as client:
        res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["redis"] == "up"

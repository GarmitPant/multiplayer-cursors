"""Robustness guards: bounded inputs and healthz."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.identity import EphemeralIdentityProvider, sanitize_display_name
from app.main import app, backplane


def test_sanitize_display_name_strips_markup_and_truncates():
    raw = "<b>" + "x" * 40 + "</b>"
    clean = sanitize_display_name(raw)
    assert "<" not in clean
    assert ">" not in clean
    assert len(clean) <= settings.max_display_name_len


def test_create_sanitizes_display_name():
    provider = EphemeralIdentityProvider()
    ident = provider.create("<evil>" + "n" * 40)
    assert "<" not in ident["name"]
    assert ">" not in ident["name"]
    assert len(ident["name"]) <= settings.max_display_name_len


def test_healthz_ok_when_redis_up():
    with patch.object(backplane, "ping", AsyncMock(return_value=None)):
        with TestClient(app) as client:
            res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["redis"] == "up"


def test_healthz_503_when_redis_down():
    with patch.object(backplane, "ping", AsyncMock(side_effect=ConnectionError("down"))):
        with TestClient(app) as client:
            res = client.get("/healthz")
    assert res.status_code == 503
    body = res.json()
    assert body["ok"] is False
    assert body["redis"] == "down"


def test_rejects_room_id_too_long():
    long_id = "a" * (settings.max_room_id_len + 1)
    with patch.object(backplane, "ping", AsyncMock(return_value=None)):
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/{long_id}?name=test") as ws:
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_text()


def test_rejects_room_at_connection_cap(monkeypatch):
    """151st connection (with cap=3) is closed with 1008 when room is full."""
    cap = 3
    monkeypatch.setattr(settings, "max_room_connections", cap)
    room = "cap-test-room"
    with patch.object(backplane, "ping", AsyncMock(return_value=None)):
        with patch.object(backplane, "publish", AsyncMock(return_value=None)):
            with TestClient(app) as client:
                holders = []
                for i in range(cap):
                    cm = client.websocket_connect(f"/ws/{room}?name=user{i}")
                    ws = cm.__enter__()
                    ws.receive_text()
                    holders.append(cm)
                with client.websocket_connect(f"/ws/{room}?name=overflow") as ws:
                    with pytest.raises(WebSocketDisconnect):
                        ws.receive_text()
                for cm in holders:
                    cm.__exit__(None, None, None)

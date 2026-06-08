"""App lifespan and remaining main.py edge paths."""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app, _evict_same_user


@pytest.mark.asyncio
async def test_evict_same_user_noop_when_room_missing():
    await _evict_same_user("missing", "u1", object())


def test_lifecycle_starts_and_stops_ticker():
    with TestClient(app) as client:
        res = client.get("/healthz")
        assert res.status_code == 200


def test_ws_cursor_leave_and_validation_drop(fast_tick):
    with TestClient(app) as client:
        with client.websocket_connect("/ws/leave-cursor?name=Me") as ws:
            json.loads(ws.receive_text())
            ws.send_text(json.dumps({"type": "cursor_leave"}))
            ws.send_text(json.dumps({"type": "cursor", "p": "not-a-tuple", "v": [0, 0], "t": 1}))

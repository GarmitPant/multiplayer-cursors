"""End-to-end tests: WebSocket + in-memory Redis pub/sub + tick batching.

Uses fakeredis (see conftest) so no live Redis is required — runs locally, in CI,
and during Render build pipelines the same way.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.protocol import quantize
from tests.helpers import recv_json, recv_until


def test_two_clients_receive_batched_cursor_frame(fast_tick):
    room = "integration-cursors"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{room}?name=Alice") as ws_a:
            init_a = recv_json(ws_a)
            assert init_a["type"] == "init"
            alice_id = init_a["self"]["user_id"]

            with client.websocket_connect(f"/ws/{room}?name=Bob") as ws_b:
                init_b = recv_json(ws_b)
                assert init_b["type"] == "init"
                assert any(p["user_id"] == alice_id for p in init_b["peers"])

                recv_until(ws_b, lambda m: m.get("type") == "peer_joined", timeout=1.0)

                ws_a.send_text(json.dumps({
                    "type": "cursor",
                    "p": [0.25, 0.75],
                    "v": [0.1, 0.0],
                    "t": 100.0,
                }))

                batched, _seen = recv_until(
                    ws_b,
                    lambda m: m.get("type") == "cursors",
                    timeout=1.5,
                )
                assert len(batched["updates"]) >= 1
            alice = next(u for u in batched["updates"] if u["user_id"] == alice_id)
            assert alice["p"] == [quantize(0.25), quantize(0.75)]
            assert alice["v"] == [0.1, 0.0]


def test_draw_stroke_relay_and_coalesced_payload(fast_tick):
    room = "integration-draw"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{room}?name=Drawer") as ws_draw:
            drawer_init = recv_json(ws_draw)
            drawer_id = drawer_init["self"]["user_id"]
            with client.websocket_connect(f"/ws/{room}?name=Watcher") as ws_watch:
                recv_json(ws_watch)
                recv_until(ws_watch, lambda m: m.get("type") == "peer_joined", timeout=1.0)

                ws_draw.send_text(json.dumps({
                    "type": "draw",
                    "seq": 1,
                    "pts": [[0.1, 0.1], [0.2, 0.2]],
                }))
                ws_draw.send_text(json.dumps({"type": "draw_end", "seq": 1}))

                draw_msg, _ = recv_until(ws_watch, lambda m: m.get("type") == "draw", timeout=1.5)
                assert draw_msg["pts"] == [[quantize(0.1), quantize(0.1)], [quantize(0.2), quantize(0.2)]]
                assert draw_msg["user_id"] == drawer_id
                assert draw_msg["seq"] == 1

                end_msg, _ = recv_until(ws_watch, lambda m: m.get("type") == "draw_end", timeout=1.5)
                assert end_msg["user_id"] == drawer_id
                assert end_msg["seq"] == 1


def test_room_teardown_clears_registry(fast_tick):
    room = "integration-teardown"
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/{room}?name=Solo") as ws:
            recv_json(ws)
        import app.main as main
        assert room not in main.rooms
        assert room not in main.caches
        assert room not in main.room_tasks

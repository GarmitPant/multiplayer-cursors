"""Test helpers for WebSocket integration tests."""
from __future__ import annotations

import json
import time


def recv_json(ws, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return json.loads(ws.receive_text())
        except Exception:
            time.sleep(0.01)
    raise TimeoutError("timed out waiting for WebSocket message")


def recv_until(ws, predicate, *, timeout: float = 2.0, max_frames: int = 20) -> tuple[dict, list[dict]]:
    seen: list[dict] = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(seen) < max_frames:
        try:
            msg = json.loads(ws.receive_text())
        except Exception:
            time.sleep(0.01)
            continue
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    types = [m.get("type") for m in seen]
    raise TimeoutError(f"no matching frame in {len(seen)} messages: {types}")

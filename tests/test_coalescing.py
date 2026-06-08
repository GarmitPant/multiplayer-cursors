from app.rooms import RoomCache


def test_cursor_last_write_wins():
    c = RoomCache()
    c.ingest({"type": "cursor", "user_id": "u1", "p": [0.1, 0.1], "v": [0, 0], "t": 1})
    c.ingest({"type": "cursor", "user_id": "u1", "p": [0.2, 0.2], "v": [0, 0], "t": 2})
    out = c.drain()
    frames = [m for m in out if m["type"] == "cursors"]
    assert len(frames) == 1
    updates = frames[0]["updates"]
    assert len(updates) == 1                     # coalesced to one
    assert updates[0]["p"] == [0.2, 0.2]         # latest wins


def test_cursor_identity_carried_from_keyframe():
    c2 = RoomCache()
    c2.ingest({"type": "cursor", "user_id": "u1", "p": [0, 0], "v": [0, 0], "t": 1,
               "kf": True, "name": "Ada", "color": "#abc"})
    c2.ingest({"type": "cursor", "user_id": "u1", "p": [0.5, 0.5], "v": [0, 0], "t": 2})
    entry = c2.drain()[0]["updates"][0]
    assert entry["name"] == "Ada" and entry["color"] == "#abc"   # identity persists through LWW


def test_draw_appends_never_drops():
    c = RoomCache()
    c.ingest({"type": "draw", "user_id": "u1", "seq": 3, "pts": [[0.1, 0.1], [0.2, 0.2]]})
    c.ingest({"type": "draw", "user_id": "u1", "seq": 3, "pts": [[0.3, 0.3]]})
    out = c.drain()
    draws = [m for m in out if m["type"] == "draw"]
    assert len(draws) == 1
    assert draws[0]["pts"] == [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]   # all points, in order


def test_draw_end_after_points():
    c = RoomCache()
    c.ingest({"type": "draw", "user_id": "u1", "seq": 4, "pts": [[0.1, 0.1]]})
    c.ingest({"type": "draw_end", "user_id": "u1", "seq": 4})
    out = c.drain()
    types = [m["type"] for m in out]
    assert types.index("draw") < types.index("draw_end")


def test_peer_left_evicts_cursor():
    c = RoomCache()
    c.ingest({"type": "cursor", "user_id": "u1", "p": [0.1, 0.1], "v": [0, 0], "t": 1})
    c.ingest({"type": "peer_left", "user_id": "u1"})
    out = c.drain()
    assert not [m for m in out if m["type"] == "cursors"]            # no stale cursor flushed
    assert any(m["type"] == "peer_left" for m in out)


def test_draw_end_without_prior_draw():
    c = RoomCache()
    c.ingest({"type": "draw_end", "user_id": "u1", "seq": 9})
    out = c.drain()
    assert [m["type"] for m in out] == ["draw_end"]


def test_drain_clears_state():
    c = RoomCache()
    c.ingest({"type": "cursor", "user_id": "u1", "p": [0, 0], "v": [0, 0], "t": 1})
    c.drain()
    assert c.empty()

"""Per-room coalescing cache for tick-batched fan-out.

Sits between the Redis relay subscription and the socket write: relay_room
ingests messages here instead of forwarding them, and the Ticker drains batched
frames to local sockets every TICK_MS.

Type-aware coalescing:
  - cursor:   last-write-wins per user
  - draw:     APPEND per (user, seq) — never drop points
  - draw_end: emitted after that stroke's pending points
  - presence: passed through in order; peer_left evicts the user's cached cursor
"""
from __future__ import annotations


class RoomCache:
    def __init__(self) -> None:
        self.cursors: dict[str, dict] = {}          # user_id -> latest cursor (LWW)
        self.strokes: dict[tuple, dict] = {}        # (user_id, seq) -> {user_id, seq, pts, ended}
        self.presence: list[dict] = []              # ordered presence messages

    def ingest(self, msg: dict) -> None:
        t = msg.get("type")
        uid = msg.get("user_id")
        if t == "cursor":
            prev = self.cursors.get(uid, {})
            entry = {"user_id": uid, "p": msg["p"], "v": msg["v"], "t": msg["t"]}
            name = msg.get("name") or prev.get("name")
            color = msg.get("color") or prev.get("color")
            if name:
                entry["name"] = name
            if color:
                entry["color"] = color
            self.cursors[uid] = entry               # last-write-wins
        elif t == "draw":
            key = (uid, msg["seq"])
            s = self.strokes.get(key)
            if s is None:
                s = self.strokes[key] = {"user_id": uid, "seq": msg["seq"], "pts": [], "ended": False}
            s["pts"].extend(msg.get("pts", []))     # APPEND — never drop, preserve order
        elif t == "draw_end":
            key = (uid, msg["seq"])
            s = self.strokes.get(key)
            if s is None:
                s = self.strokes[key] = {"user_id": uid, "seq": msg["seq"], "pts": [], "ended": False}
            s["ended"] = True
        elif t in ("peer_joined", "peer_left", "cursor_leave", "tick_ms"):
            self.presence.append(msg)
            if t == "peer_left":
                self.cursors.pop(uid, None)         # don't flush a departed user's cursor
        # heartbeat / unknown: ignored

    def empty(self) -> bool:
        return not (self.cursors or self.strokes or self.presence)

    def drain(self) -> list[dict]:
        """Ordered batched messages to fan out this tick; clears pending state."""
        out: list[dict] = []
        out.extend(self.presence)                                   # 1) presence first
        for s in self.strokes.values():                            # 2) draw (append), then draw_end
            if s["pts"]:
                out.append({"type": "draw", "user_id": s["user_id"], "seq": s["seq"], "pts": s["pts"]})
            if s["ended"]:
                out.append({"type": "draw_end", "user_id": s["user_id"], "seq": s["seq"]})
        if self.cursors:                                           # 3) one coalesced cursor frame
            out.append({"type": "cursors", "updates": list(self.cursors.values())})
        self.presence = []
        self.strokes = {}
        self.cursors = {}
        return out

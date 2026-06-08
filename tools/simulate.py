"""Open N websocket clients into one room, each sending cursor updates at ~20Hz.

Uses human-like wandering paths + send-on-delta (matches client emitter) so load tests
measure realistic message rates, not random-position noise.

Optional draw mode mirrors the client draw pipeline (Bézier path → One Euro → RDP).

Usage:
  python tools/simulate.py ws://localhost:8080/ws/demo 100
  python tools/simulate.py ws://localhost:8080/ws/demo 20 --draw-frac 0.5
  python tools/simulate.py ws://localhost:8080/ws/demo 20 --draw-frac 1.0 --draw-only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from draw_pipeline import (  # noqa: E402
    ONE_EURO_BETA,
    ONE_EURO_MINCUTOFF,
    EPS_RDP,
    DRAW_WINDOW,
    OneEuro,
    StrokeSimplifier,
    generate_bezier_stroke,
)

HZ = 20
EPS_POS = 0.005
VEL_SMOOTH = 0.5
KEYFRAME_MS = 1500
COLORS = ["#4a9eed", "#22c55e", "#f59e0b", "#ef4444",
          "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]


def predict_position(p0, v0, t0, t):
    dt = t - t0
    return (p0[0] + v0[0] * dt, p0[1] + v0[1] * dt)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def should_emit_delta(belief, p_real, t, eps_pos=EPS_POS):
    if belief is None:
        return True
    p_pred = predict_position(belief["p"], belief["v"], belief["t"], t)
    return distance(p_real, p_pred) > eps_pos


def smooth_velocity(prev_v, raw_v, alpha=VEL_SMOOTH):
    if prev_v is None:
        return raw_v
    return (
        alpha * raw_v[0] + (1 - alpha) * prev_v[0],
        alpha * raw_v[1] + (1 - alpha) * prev_v[1],
    )


class HumanPath:
    """Smooth wandering curve with occasional pauses and sharp retargets."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.x = self.rng.random()
        self.y = self.rng.random()
        self.tx = self.rng.random()
        self.ty = self.rng.random()
        self.phase = self.rng.random() * math.tau
        self.pause_until = 0.0
        self.speed = self.rng.uniform(0.02, 0.06)

    def sample(self, t: float) -> tuple[float, float]:
        if t < self.pause_until:
            return self._clamp(self.x, self.y)

        if self.rng.random() < 0.003:
            self.pause_until = t + self.rng.uniform(0.4, 1.8)

        if self.rng.random() < 0.012:
            self.tx = self.rng.random()
            self.ty = self.rng.random()
            self.speed = self.rng.uniform(0.02, 0.08)

        drift_x = math.sin(t * 0.9 + self.phase) * 0.004
        drift_y = math.cos(t * 0.7 + self.phase * 1.3) * 0.004
        self.x += (self.tx - self.x) * self.speed + drift_x
        self.y += (self.ty - self.y) * self.speed + drift_y
        return self._clamp(self.x, self.y)

    @staticmethod
    def _clamp(x: float, y: float) -> tuple[float, float]:
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))


async def send_draw_pts(ws, stats: dict, seq: int, pts) -> None:
    if not pts:
        return
    await ws.send(json.dumps({
        "type": "draw",
        "seq": seq,
        "pts": [[p[0], p[1]] for p in pts],
    }))
    stats["draw_pts"] += len(pts)


async def send_cursor_msg(
    ws,
    i: int,
    stats: dict,
    p: tuple[float, float],
    t: float,
    v: tuple[float, float],
    *,
    keyframe: bool = False,
) -> None:
    msg = {
        "type": "cursor",
        "p": list(p),
        "v": list(v),
        "t": t,
    }
    if keyframe:
        msg["kf"] = True
        msg["name"] = f"bot{i}"
        msg["color"] = COLORS[i % len(COLORS)]
    await ws.send(json.dumps(msg))
    stats["sent"] += 1


class CursorEmitter:
    """Send-on-delta cursor helper (matches client Emitter)."""

    def __init__(self):
        self.belief = None
        self.prev_p = None
        self.prev_t = None
        self.v_smooth = None
        self.last_kf = 0.0

    async def emit(
        self,
        ws,
        i: int,
        stats: dict,
        p: tuple[float, float],
        t: float,
        *,
        force_keyframe: bool = False,
    ) -> None:
        raw_v = (0.0, 0.0)
        if self.prev_p is not None and self.prev_t is not None:
            dt = t - self.prev_t
            if dt > 0:
                raw_v = ((p[0] - self.prev_p[0]) / dt, (p[1] - self.prev_p[1]) / dt)
        v_new = smooth_velocity(self.v_smooth, raw_v)
        self.v_smooth = v_new
        self.prev_p, self.prev_t = p, t

        now_ms = t * 1000
        if force_keyframe or now_ms - self.last_kf >= KEYFRAME_MS:
            self.last_kf = now_ms
            await send_cursor_msg(ws, i, stats, p, t, v_new, keyframe=True)
            self.belief = {"p": p, "v": v_new, "t": t}
            return

        if should_emit_delta(self.belief, p, t):
            await send_cursor_msg(ws, i, stats, p, t, v_new)
            self.belief = {"p": p, "v": v_new, "t": t}


async def cursor_loop(ws, i: int, stats: dict, path: HumanPath, t0: float) -> None:
    emitter = CursorEmitter()
    while True:
        await asyncio.sleep(1 / HZ)
        t = time.time() - t0
        p = path.sample(t)
        await emitter.emit(ws, i, stats, p, t)


async def idle_with_cursor(
    ws,
    i: int,
    stats: dict,
    emitter: CursorEmitter,
    t0: float,
    seconds: float,
    hold: tuple[float, float] | None,
) -> None:
    """Sleep in slices, refreshing cursor keyframes so peers stay visible."""
    if hold is None:
        await asyncio.sleep(seconds)
        return
    end = time.time() + seconds
    while time.time() < end:
        await emitter.emit(ws, i, stats, hold, time.time() - t0, force_keyframe=False)
        await asyncio.sleep(min(0.5, end - time.time()))


async def draw_loop(ws, i: int, stats: dict, rng: random.Random, t0: float) -> None:
    """Draw strokes and emit cursor frames at the pen tip (name + color on keyframes)."""
    emitter = CursorEmitter()
    last_tip: tuple[float, float] | None = None
    seq = 0

    while True:
        await idle_with_cursor(ws, i, stats, emitter, t0, rng.uniform(0.5, 2.5), last_tip)
        seq += 1
        stroke_duration = rng.uniform(0.3, 0.8)
        emit_hz = rng.uniform(30, 60)
        step = 1.0 / emit_hz

        raw_path = generate_bezier_stroke(rng, n_samples=60)
        euro_x = OneEuro(ONE_EURO_MINCUTOFF, ONE_EURO_BETA)
        euro_y = OneEuro(ONE_EURO_MINCUTOFF, ONE_EURO_BETA)
        simplifier = StrokeSimplifier(raw_path[0], EPS_RDP, DRAW_WINDOW)

        stroke_t0 = time.time()
        filter_t = stroke_t0 - t0
        tip = (euro_x.filter(raw_path[0][0], filter_t), euro_y.filter(raw_path[0][1], filter_t))
        await emitter.emit(ws, i, stats, tip, filter_t, force_keyframe=True)
        await send_draw_pts(ws, stats, seq, simplifier.stroke_origin())

        captured = 1
        next_emit = stroke_t0 + step
        for raw in raw_path[1:]:
            now = time.time()
            if now < next_emit:
                await asyncio.sleep(next_emit - now)
            filter_t = time.time() - t0
            tip = (euro_x.filter(raw[0], filter_t), euro_y.filter(raw[1], filter_t))
            captured += 1
            emitted = simplifier.push(list(tip))
            if emitted:
                await send_draw_pts(ws, stats, seq, emitted)
            await emitter.emit(ws, i, stats, tip, filter_t)
            last_tip = tip
            next_emit += step

        rest = simplifier.flush()
        if rest:
            await send_draw_pts(ws, stats, seq, rest)
            last_tip = rest[-1]
            await emitter.emit(ws, i, stats, last_tip, time.time() - t0)

        await ws.send(json.dumps({"type": "draw_end", "seq": seq}))
        stats["draw_strokes"] += 1
        stats["draw_captured"] += captured

        elapsed = time.time() - stroke_t0
        if elapsed < stroke_duration:
            await idle_with_cursor(
                ws, i, stats, emitter, t0, stroke_duration - elapsed, last_tip,
            )


async def client(
    i: int,
    stats: dict,
    url: str,
    *,
    draws: bool,
) -> None:
    path = HumanPath(seed=i * 9973 + 42)
    rng = random.Random(i * 7919 + 3)
    t0 = time.time()
    # Drawing bots track the pen tip; wandering HumanPath is for non-drawers only.
    skip_wander_cursor = draws

    async with websockets.connect(f"{url}?name=bot{i}") as ws:
        async def recv():
            async for raw in ws:
                stats["recv_msgs"] += 1
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                if m.get("type") == "cursors":
                    stats["recv_pos"] += len(m.get("updates", []))
                elif m.get("type") == "cursor":
                    stats["recv_pos"] += 1

        recv_task = asyncio.create_task(recv())
        try:
            runners = []
            if not skip_wander_cursor:
                runners.append(cursor_loop(ws, i, stats, path, t0))
            if draws:
                runners.append(draw_loop(ws, i, stats, rng, t0))
            if runners:
                await asyncio.gather(*runners)
        finally:
            recv_task.cancel()


def pick_draw_bots(n: int, draw_frac: float) -> set[int]:
    k = int(n * draw_frac)
    if k <= 0:
        return set()
    k = min(k, n)
    return set(random.Random(0).sample(range(n), k))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate N websocket clients with human-like cursor paths.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python tools/simulate.py ws://localhost:8080/ws/demo 20 --draw-frac 0.5\n"
            "  python tools/simulate.py ws://localhost:8080/ws/demo 20 --draw-frac 1.0 --draw-only"
        ),
    )
    parser.add_argument("ws_url", nargs="?", default="ws://localhost:8080/ws/demo")
    parser.add_argument("n", nargs="?", type=int, default=100)
    parser.add_argument(
        "--draw-frac",
        type=float,
        default=0.0,
        help="fraction of bots that periodically draw strokes (default: 0.0)",
    )
    parser.add_argument(
        "--draw-only",
        action="store_true",
        help="drawing bots skip wandering cursor paths; cursor follows the pen tip only",
    )
    return parser.parse_args(argv)


async def main(args: argparse.Namespace) -> None:
    draw_bots = pick_draw_bots(args.n, args.draw_frac)
    stats = {
        "sent": 0,
        "recv_msgs": 0,
        "recv_pos": 0,
        "draw_pts": 0,
        "draw_strokes": 0,
        "draw_captured": 0,
    }
    for i in range(args.n):
        asyncio.create_task(client(
            i,
            stats,
            args.ws_url,
            draws=i in draw_bots,
        ))
    t0 = time.time()
    while True:
        await asyncio.sleep(2)
        dt = time.time() - t0
        cap_rate = stats["draw_captured"] / dt if dt > 0 else 0.0
        pts_rate = stats["draw_pts"] / dt if dt > 0 else 0.0
        print(
            f"[{dt:5.1f}s] clients={args.n} draw_bots={len(draw_bots)} "
            f"sent/s={stats['sent']/dt:7.0f} "
            f"recv_msgs/s={stats['recv_msgs']/dt:8.0f} recv_pos/s={stats['recv_pos']/dt:8.0f} "
            f"draw_pts/s={pts_rate:8.1f} strokes/s={stats['draw_strokes']/dt:6.2f} "
            f"(captured/s={cap_rate:6.0f})"
        )


if __name__ == "__main__":
    asyncio.run(main(parse_args(sys.argv[1:])))

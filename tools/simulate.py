"""Open N websocket clients into one room, each sending cursor updates at ~20Hz.

Uses human-like wandering paths + send-on-delta (matches client M2) so load tests
measure realistic message rates, not random-position noise.

Usage: python tools/simulate.py [ws_url] [n]
"""
import asyncio
import json
import math
import random
import sys
import time

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8080/ws/demo"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
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


async def client(i: int, stats: dict):
    path = HumanPath(seed=i * 9973 + 42)
    belief = None
    prev_p = None
    prev_t = None
    v_smooth = None
    last_kf = 0.0
    t0 = time.time()

    async with websockets.connect(f"{URL}?name=bot{i}") as ws:
        async def recv():
            async for _ in ws:
                stats["recv"] += 1

        task = asyncio.create_task(recv())
        try:
            while True:
                await asyncio.sleep(1 / HZ)
                t = time.time() - t0
                p = path.sample(t)

                raw_v = (0.0, 0.0)
                if prev_p is not None and prev_t is not None:
                    dt = t - prev_t
                    if dt > 0:
                        raw_v = ((p[0] - prev_p[0]) / dt, (p[1] - prev_p[1]) / dt)
                v_new = smooth_velocity(v_smooth, raw_v)
                v_smooth = v_new
                prev_p, prev_t = p, t

                now_ms = t * 1000
                if now_ms - last_kf >= KEYFRAME_MS:
                    last_kf = now_ms
                    msg = {
                        "type": "cursor",
                        "p": list(p),
                        "v": list(v_new),
                        "t": t,
                        "kf": True,
                        "name": f"bot{i}",
                        "color": COLORS[i % len(COLORS)],
                    }
                    await ws.send(json.dumps(msg))
                    stats["sent"] += 1
                    belief = {"p": p, "v": v_new, "t": t}
                    continue

                if should_emit_delta(belief, p, t):
                    await ws.send(json.dumps({
                        "type": "cursor",
                        "p": list(p),
                        "v": list(v_new),
                        "t": t,
                    }))
                    stats["sent"] += 1
                    belief = {"p": p, "v": v_new, "t": t}
        finally:
            task.cancel()


async def main():
    stats = {"sent": 0, "recv": 0}
    [asyncio.create_task(client(i, stats)) for i in range(N)]
    t0 = time.time()
    while True:
        await asyncio.sleep(2)
        dt = time.time() - t0
        print(f"[{dt:5.1f}s] clients={N} "
              f"sent/s={stats['sent']/dt:8.0f} recv/s={stats['recv']/dt:9.0f}")


if __name__ == "__main__":
    asyncio.run(main())

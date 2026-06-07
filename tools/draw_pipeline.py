"""M4 draw pipeline helpers (Python mirror of client/cursorEngine.js). Used by simulate + tests."""
from __future__ import annotations

import math
import random

EPS_RDP = 0.003
DRAW_WINDOW = 16
ONE_EURO_MINCUTOFF = 1.0
ONE_EURO_BETA = 0.007
DCUTOFF = 1.0

PI = math.pi


def clamp01(x: float, y: float) -> tuple[float, float]:
    return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))


def distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def perp_distance(p, a, b) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0 and dy == 0:
        return distance(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    px = a[0] + t * dx
    py = a[1] + t * dy
    return distance(p, (px, py))


def rdp(points, eps: float = EPS_RDP):
    if len(points) <= 2:
        return [(p[0], p[1]) for p in points]
    first = points[0]
    last = points[-1]
    max_dist = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        d = perp_distance(points[i], first, last)
        if d > max_dist:
            max_dist = d
            index = i
    if max_dist > eps:
        left = rdp(points[: index + 1], eps)
        right = rdp(points[index:], eps)
        return left[:-1] + right
    return [(first[0], first[1]), (last[0], last[1])]


def lowpass(x: float, prev: float, a: float) -> float:
    return a * x + (1 - a) * prev


def euro_alpha(cutoff: float, dt: float) -> float:
    return 1 / (1 + (1 / (2 * PI * cutoff)) / dt)


class OneEuro:
    def __init__(
        self,
        mincutoff: float = ONE_EURO_MINCUTOFF,
        beta: float = ONE_EURO_BETA,
        dcutoff: float = DCUTOFF,
    ):
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self.x_prev: float | None = None
        self.dx_prev = 0.0
        self.t_prev: float | None = None

    def reset(self) -> None:
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def filter(self, x: float, t: float) -> float:
        if self.x_prev is None:
            self.x_prev = x
            self.dx_prev = 0.0
            self.t_prev = t
            return x
        dt = max(1e-6, t - self.t_prev)
        dx = (x - self.x_prev) / dt
        a_d = euro_alpha(self.dcutoff, dt)
        edx = lowpass(dx, self.dx_prev, a_d)
        cutoff = self.mincutoff + self.beta * abs(edx)
        a_x = euro_alpha(cutoff, dt)
        x_filt = lowpass(x, self.x_prev, a_x)
        self.x_prev = x_filt
        self.dx_prev = edx
        self.t_prev = t
        return x_filt


class StrokeSimplifier:
    def __init__(self, anchor, eps: float = EPS_RDP, window_size: int = DRAW_WINDOW):
        self.eps = eps
        self.window_size = window_size
        self.anchor = [anchor[0], anchor[1]]
        self.buffer = [[anchor[0], anchor[1]]]

    def stroke_origin(self):
        return [[self.anchor[0], self.anchor[1]]]

    def push(self, point):
        self.buffer.append([point[0], point[1]])
        if len(self.buffer) >= self.window_size:
            return self._emit_window()
        return []

    def _emit_window(self):
        simplified = rdp(self.buffer, self.eps)
        to_emit = simplified[1:] if len(simplified) > 1 else []
        last_raw = self.buffer[-1]
        self.anchor = [last_raw[0], last_raw[1]]
        self.buffer = [[self.anchor[0], self.anchor[1]]]
        return to_emit

    def flush(self):
        if len(self.buffer) <= 1:
            return []
        simplified = rdp(self.buffer, self.eps)
        to_emit = simplified[1:] if len(simplified) > 1 else []
        self.buffer = [[self.anchor[0], self.anchor[1]]]
        return to_emit


def cubic_bezier(p0, p1, p2, p3, t: float) -> tuple[float, float]:
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return clamp01(x, y)


def generate_bezier_stroke(rng: random.Random, n_samples: int = 60) -> list[tuple[float, float]]:
    """Smooth curved drag path between random endpoints (cubic Bézier)."""
    p0 = (rng.uniform(0.08, 0.92), rng.uniform(0.08, 0.92))
    p3 = (rng.uniform(0.08, 0.92), rng.uniform(0.08, 0.92))
    p1 = clamp01(p0[0] + rng.uniform(-0.35, 0.35), p0[1] + rng.uniform(-0.35, 0.35))
    p2 = clamp01(p3[0] + rng.uniform(-0.35, 0.35), p3[1] + rng.uniform(-0.35, 0.35))
    if n_samples < 2:
        n_samples = 2
    return [cubic_bezier(p0, p1, p2, p3, i / (n_samples - 1)) for i in range(n_samples)]

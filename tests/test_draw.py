"""Tests for M4 draw trail pure functions (mirrored from client/cursorEngine.js)."""
import math

from hypothesis import given, settings as hyp_settings, strategies as st

EPS_RDP = 0.003
DCUTOFF = 1.0
ONE_EURO_MINCUTOFF = 1.0
ONE_EURO_BETA = 0.007


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def perp_distance(p, a, b):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0 and dy == 0:
        return distance(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    px = a[0] + t * dx
    py = a[1] + t * dy
    return distance(p, (px, py))


def rdp(points, eps):
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


def cr_point(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return (
        0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
               + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
               + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
        0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
               + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
               + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
    )


def catmull_rom(control_pts, segs=8):
    if not control_pts:
        return []
    if len(control_pts) == 1:
        return [(control_pts[0][0], control_pts[0][1])]
    pts = [(p[0], p[1]) for p in control_pts]
    n = len(pts)

    def get(i):
        if i < 0:
            return pts[0]
        if i >= n:
            return pts[n - 1]
        return pts[i]

    out = []
    for i in range(n - 1):
        p0, p1, p2, p3 = get(i - 1), get(i), get(i + 1), get(i + 2)
        limit = segs if i == n - 2 else segs - 1
        for s in range(limit + 1):
            out.append(cr_point(p0, p1, p2, p3, s / segs))
    return out


PI = math.pi


def lowpass(x, prev, a):
    return a * x + (1 - a) * prev


def euro_alpha(cutoff, dt):
    return 1 / (1 + (1 / (2 * PI * cutoff)) / dt)


class OneEuro:
    def __init__(self, mincutoff, beta, dcutoff=DCUTOFF):
        self.mincutoff = mincutoff
        self.beta = beta
        self.dcutoff = dcutoff
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def filter(self, x, t):
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


def test_rdp_preserves_endpoints():
    pts = [(0.0, 0.0), (0.25, 0.01), (0.5, 0.02), (0.75, 0.01), (1.0, 0.0)]
    out = rdp(pts, EPS_RDP)
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]
    assert len(out) < len(pts)


def test_rdp_collinear_reduces_to_endpoints():
    pts = [(i / 10, i / 10) for i in range(11)]
    out = rdp(pts, EPS_RDP)
    assert len(out) == 2
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]


def test_rdp_idempotent_on_result():
    pts = [(0, 0), (0.2, 0.5), (0.4, 0.52), (0.6, 0.55), (0.8, 0.9), (1, 1)]
    once = rdp(pts, EPS_RDP)
    twice = rdp(once, EPS_RDP)
    assert once == twice


def test_catmull_rom_passes_through_controls():
    controls = [(0.1, 0.2), (0.3, 0.7), (0.6, 0.4), (0.9, 0.8)]
    dense = catmull_rom(controls, segs=16)
    assert len(dense) > len(controls)
    for c in controls:
        assert min(distance(c, d) for d in dense) < 0.02


def test_catmull_rom_finite():
    controls = [(0.0, 0.0), (0.2, 0.8), (0.5, 0.5), (1.0, 1.0)]
    for x, y in catmull_rom(controls, segs=8):
        assert math.isfinite(x) and math.isfinite(y)


def test_one_euro_reduces_jitter():
    filt = OneEuro(ONE_EURO_MINCUTOFF, ONE_EURO_BETA)
    t = 0.0
    raw = []
    filtered = []
    for i in range(50):
        t += 0.016
        x = 0.5 + 0.02 * math.sin(i * 0.7) + (0.01 if i % 3 == 0 else 0)
        raw.append(x)
        filtered.append(filt.filter(x, t))
    raw_var = max(raw) - min(raw)
    filt_var = max(filtered) - min(filtered)
    assert filt_var <= raw_var + 1e-9

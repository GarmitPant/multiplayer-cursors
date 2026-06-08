"""Tests for draw trail pure functions (mirrored from client/cursorEngine.js)."""
import math
import random

from draw_pipeline import (
    EPS_RDP,
    ONE_EURO_BETA,
    ONE_EURO_MINCUTOFF,
    OneEuro,
    generate_bezier_stroke,
    rdp,
)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


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


def test_bezier_stroke_in_unit_square():
    pts = generate_bezier_stroke(random.Random(1), n_samples=60)
    assert len(pts) == 60
    for x, y in pts:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


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

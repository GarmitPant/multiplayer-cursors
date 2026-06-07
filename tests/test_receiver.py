"""Property tests for M3 receive-side reconstruction (mirrored from client/index.html)."""
import math

from hypothesis import given, settings as hyp_settings, strategies as st

BLEND_MS = 100
CLAMP_MS = 2000
PRESENCE_TIMEOUT_MS = 5000


def predict_position(p0, v0, t0, t):
    dt = t - t0
    return (p0[0] + v0[0] * dt, p0[1] + v0[1] * dt)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def blend_toward(p_render, target, dt_sec, blend_ms=BLEND_MS):
    factor = min(1.0, dt_sec * 1000.0 / blend_ms)
    return (
        p_render[0] + (target[0] - p_render[0]) * factor,
        p_render[1] + (target[1] - p_render[1]) * factor,
    )


def decay_velocity(v, silence_ms, clamp_ms=CLAMP_MS):
    if silence_ms <= clamp_ms:
        return v
    t = (silence_ms - clamp_ms) / clamp_ms
    k = max(0.0, 1.0 - t)
    return (v[0] * k, v[1] * k)


def should_drop_peer(silence_ms, presence_timeout_ms=PRESENCE_TIMEOUT_MS):
    return silence_ms > presence_timeout_ms


# Feature: collaborative-cursor-scaffold, Property 4: Predictor determinism
@hyp_settings(max_examples=100)
@given(
    px=st.floats(min_value=-10, max_value=10, allow_nan=False, allow_infinity=False),
    py=st.floats(min_value=-10, max_value=10, allow_nan=False, allow_infinity=False),
    vx=st.floats(min_value=-10, max_value=10, allow_nan=False, allow_infinity=False),
    vy=st.floats(min_value=-10, max_value=10, allow_nan=False, allow_infinity=False),
    t0=st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
    dt=st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
)
def test_predictor_determinism(px, py, vx, vy, t0, dt):
    p = (px, py)
    v = (vx, vy)
    t = t0 + dt
    result = predict_position(p, v, t0, t)
    expected = (p[0] + v[0] * dt, p[1] + v[1] * dt)
    assert math.isclose(result[0], expected[0], rel_tol=0, abs_tol=1e-9)
    assert math.isclose(result[1], expected[1], rel_tol=0, abs_tol=1e-9)
    assert predict_position(p, v, t0, t0) == p
    assert math.isfinite(result[0]) and math.isfinite(result[1])


def _on_segment(start, end, point, eps=1e-9):
    for i in range(2):
        lo = min(start[i], end[i]) - eps
        hi = max(start[i], end[i]) + eps
        if not (lo <= point[i] <= hi):
            return False
    return True


# Feature: collaborative-cursor-scaffold, Property 11: Velocity-blend convergence without overshoot
@hyp_settings(max_examples=100)
@given(
    rx=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
    ry=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
    tx=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
    ty=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
    steps=st.integers(min_value=1, max_value=30),
)
def test_blend_convergence_without_overshoot(rx, ry, tx, ty, steps):
    start = (rx, ry)
    p_render = start
    target = (tx, ty)
    dt = BLEND_MS / 1000.0 / steps
    prev_d = distance(p_render, target)
    for _ in range(steps):
        p_render = blend_toward(p_render, target, dt)
        d = distance(p_render, target)
        assert d <= prev_d + 1e-9
        prev_d = d
        assert math.isfinite(p_render[0]) and math.isfinite(p_render[1])
        assert _on_segment(start, target, p_render)
    assert blend_toward(target, target, dt) == target


@hyp_settings(max_examples=100)
@given(
    vx=st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
    vy=st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
    extra=st.floats(min_value=0, max_value=CLAMP_MS * 2, allow_nan=False, allow_infinity=False),
)
def test_velocity_clamp_decays_to_zero(vx, vy, extra):
    v = (vx, vy)
    silence = CLAMP_MS + extra
    out = decay_velocity(v, silence)
    mag_in = math.hypot(v[0], v[1])
    mag_out = math.hypot(out[0], out[1])
    assert mag_out <= mag_in + 1e-12
    if extra >= CLAMP_MS:
        assert mag_out < 1e-9 or mag_in < 1e-9


def test_presence_timeout_drops_peer():
    assert not should_drop_peer(PRESENCE_TIMEOUT_MS)
    assert should_drop_peer(PRESENCE_TIMEOUT_MS + 1)

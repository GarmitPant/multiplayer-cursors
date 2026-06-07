"""Property tests for M3 receive-side reconstruction (mirrored from client/index.html)."""
import math

from hypothesis import given, settings as hyp_settings, strategies as st

CLAMP_GRACE_MS = 80
CLAMP_ZERO_MS = 300
PRESENCE_TIMEOUT_MS = 5000
SMOOTH_TIME = 0.08


def predict_position(p0, v0, t0, t):
    dt = t - t0
    return (p0[0] + v0[0] * dt, p0[1] + v0[1] * dt)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def smooth_damp(current, target, vel, smooth_time, dt):
    omega = 2 / smooth_time
    x = omega * dt
    exp = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - target
    temp = (vel + omega * change) * dt
    new_vel = (vel - omega * temp) * exp
    return target + (change + temp) * exp, new_vel


def decay_velocity(v, silence_ms, grace_ms=CLAMP_GRACE_MS, zero_ms=CLAMP_ZERO_MS):
    if silence_ms <= grace_ms:
        return v
    if silence_ms >= zero_ms:
        return (0.0, 0.0)
    k = 1 - (silence_ms - grace_ms) / (zero_ms - grace_ms)
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


def _on_segment(start, end, point, eps=1e-6):
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
    steps=st.integers(min_value=5, max_value=60),
)
def test_smooth_damp_convergence_without_overshoot(rx, ry, tx, ty, steps):
    start = (rx, ry)
    pos = start
    vel = 0.0
    target = (tx, ty)
    dt = SMOOTH_TIME / steps
    prev_d = distance(pos, target)
    for _ in range(steps):
        pos_x, vel_x = smooth_damp(pos[0], target[0], vel, SMOOTH_TIME, dt)
        pos_y, vel_y = smooth_damp(pos[1], target[1], vel, SMOOTH_TIME, dt)
        pos = (pos_x, pos_y)
        d = distance(pos, target)
        assert d <= prev_d + 1e-6
        prev_d = d
        assert math.isfinite(pos[0]) and math.isfinite(pos[1])
        assert _on_segment(start, target, pos)
    fixed, v = smooth_damp(target[0], target[0], 0.0, SMOOTH_TIME, dt)
    assert math.isclose(fixed, target[0], abs_tol=1e-9)
    assert math.isclose(v, 0.0, abs_tol=1e-6)


@hyp_settings(max_examples=100)
@given(
    vx=st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
    vy=st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
    silence=st.floats(min_value=0, max_value=CLAMP_ZERO_MS * 2, allow_nan=False, allow_infinity=False),
)
def test_velocity_clamp_decays_to_zero(vx, vy, silence):
    v = (vx, vy)
    out = decay_velocity(v, silence)
    mag_in = math.hypot(v[0], v[1])
    mag_out = math.hypot(out[0], out[1])
    assert mag_out <= mag_in + 1e-12
    if silence >= CLAMP_ZERO_MS:
        assert mag_out < 1e-9


def test_presence_timeout_drops_peer():
    assert not should_drop_peer(PRESENCE_TIMEOUT_MS)
    assert should_drop_peer(PRESENCE_TIMEOUT_MS + 1)

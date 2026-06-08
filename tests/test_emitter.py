"""Property tests for send-on-delta emitter logic.

Approach: pure functions mirrored from client/cursorEngine.js (Python equivalents).
"""
import math

from hypothesis import given, settings as hyp_settings, strategies as st

EPS_POS = 0.005
VEL_SMOOTH = 0.5


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


def reset_belief(p_real, v_new, t):
    return {"p": p_real, "v": v_new, "t": t}


# Property: send-on-delta correctness
@hyp_settings(max_examples=100)
@given(
    p0=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    p1=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    v0x=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    v0y=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    t0=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    dt=st.floats(min_value=1e-6, max_value=10.0, allow_nan=False, allow_infinity=False),
    px=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    py=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_send_on_delta_correctness(p0, p1, v0x, v0y, t0, dt, px, py):
    belief = {"p": (p0, p1), "v": (v0x, v0y), "t": t0}
    t = t0 + dt
    p_real = (px, py)
    emit = should_emit_delta(belief, p_real, t)
    p_pred = predict_position(belief["p"], belief["v"], belief["t"], t)
    assert emit == (distance(p_real, p_pred) > EPS_POS)

    if emit:
        v_new = (0.1, -0.2)
        new_belief = reset_belief(p_real, v_new, t)
        p_at_t = predict_position(new_belief["p"], new_belief["v"], new_belief["t"], t)
        assert distance(p_at_t, p_real) < 1e-9


@hyp_settings(max_examples=100)
@given(t=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_first_sample_always_emits(t):
    assert should_emit_delta(None, (0.5, 0.5), t)


# Property: velocity estimator convergence and boundedness
@hyp_settings(max_examples=100)
@given(
    v_true_x=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    v_true_y=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    n=st.integers(min_value=10, max_value=80),
)
def test_velocity_estimator_convergence(v_true_x, v_true_y, n):
    v_true = (v_true_x, v_true_y)
    v_smooth = None
    prev_p = (0.5, 0.5)
    raw_vs = []
    for _ in range(n):
        p = (prev_p[0] + v_true[0] * 0.05, prev_p[1] + v_true[1] * 0.05)
        raw_v = (v_true[0], v_true[1])
        raw_vs.append(raw_v)
        v_smooth = smooth_velocity(v_smooth, raw_v)
        prev_p = p
        assert math.isfinite(v_smooth[0]) and math.isfinite(v_smooth[1])
        lo_x = min(rv[0] for rv in raw_vs)
        hi_x = max(rv[0] for rv in raw_vs)
        lo_y = min(rv[1] for rv in raw_vs)
        hi_y = max(rv[1] for rv in raw_vs)
        assert lo_x - 1e-9 <= v_smooth[0] <= hi_x + 1e-9
        assert lo_y - 1e-9 <= v_smooth[1] <= hi_y + 1e-9
    assert distance(v_smooth, v_true) < 0.05

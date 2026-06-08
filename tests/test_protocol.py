import pytest
from hypothesis import given, settings as hyp_settings, strategies as st
from pydantic import ValidationError

from app.config import settings as app_settings
from app.protocol import (
    MAX_PTS_PER_MSG,
    _clamp01,
    parse_inbound,
    quantize,
)


# ── valid §7 shapes ──────────────────────────────────────────────────────────

def test_valid_cursor_delta():
    m = parse_inbound({"type": "cursor", "p": [0.42, 0.61], "v": [0.8, -0.2], "t": 1730000000.0})
    assert m.type == "cursor"
    assert m.p == (quantize(0.42), quantize(0.61))


def test_valid_cursor_keyframe():
    m = parse_inbound({
        "type": "cursor", "p": [0.5, 0.5], "v": [0.0, 0.0], "t": 1.0,
        "kf": True, "name": "Ada", "color": "#4a9eed",
    })
    assert m.kf is True
    assert m.name == "Ada"
    assert m.color == "#4a9eed"


def test_valid_cursor_leave():
    m = parse_inbound({"type": "cursor_leave"})
    assert m.type == "cursor_leave"


def test_valid_draw():
    m = parse_inbound({"type": "draw", "seq": 7, "pts": [[0.40, 0.60], [0.41, 0.61]]})
    assert m.seq == 7
    assert len(m.pts) == 2


def test_valid_draw_end():
    m = parse_inbound({"type": "draw_end", "seq": 7})
    assert m.type == "draw_end"


def test_valid_heartbeat():
    m = parse_inbound({"type": "heartbeat"})
    assert m.type == "heartbeat"


def test_valid_set_tick_ms():
    m = parse_inbound({"type": "set_tick_ms", "value": 50})
    assert m.type == "set_tick_ms"
    assert m.value == 50


def test_set_tick_ms_accepts_minimum():
    m = parse_inbound({"type": "set_tick_ms", "value": 1})
    assert m.value == 1


def test_set_tick_ms_clamps_low():
    with pytest.raises(ValidationError):
        parse_inbound({"type": "set_tick_ms", "value": 0})


def test_set_tick_ms_clamps_high():
    with pytest.raises(ValidationError):
        parse_inbound({"type": "set_tick_ms", "value": 501})


# ── malformed / rejected ─────────────────────────────────────────────────────

def test_missing_required_fields_raises():
    with pytest.raises(ValidationError):
        parse_inbound({"type": "cursor", "p": [0.5, 0.5]})


def test_wrong_typed_field_raises():
    with pytest.raises(ValidationError):
        parse_inbound({"type": "cursor", "p": [0.5, 0.5], "v": "bad", "t": 1.0})


def test_extra_field_forbidden_raises():
    with pytest.raises(ValidationError):
        parse_inbound({
            "type": "cursor", "p": [0.5, 0.5], "v": [0.0, 0.0], "t": 1.0,
            "unexpected": True,
        })


def test_oversized_draw_raises():
    pts = [[0.5, 0.5] for _ in range(MAX_PTS_PER_MSG + 1)]
    with pytest.raises(ValidationError):
        parse_inbound({"type": "draw", "seq": 0, "pts": pts})


def test_unknown_type_returns_none():
    assert parse_inbound({"type": "bogus"}) is None


# Feature: collaborative-cursor-scaffold, Property 8: Quantization round-trip and idempotence
@hyp_settings(max_examples=100)
@given(x=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_quantize_round_trip_and_idempotent(x):
    bits = app_settings.quant_bits
    levels = (1 << bits) - 1
    step = 1.0 / levels
    q = quantize(x)
    assert abs(q - round(q * levels) / levels) < 1e-12
    assert abs(q - x) <= step + 1e-12
    assert quantize(q) == q


# Feature: collaborative-cursor-scaffold, Property 7: Coordinate clamping is total and range-preserving
@hyp_settings(max_examples=100)
@given(x=st.floats(allow_nan=False, allow_infinity=False))
def test_clamp01_total_and_range_preserving(x):
    c = _clamp01(x)
    assert 0.0 <= c <= 1.0
    if 0.0 <= x <= 1.0:
        assert c == x

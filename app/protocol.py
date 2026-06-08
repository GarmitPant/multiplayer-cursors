# app/protocol.py — LLD phase: validate, clamp, quantize. No relay logic here.
from typing import Literal, Optional, Annotated
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .config import settings  # QUANT_BITS lives in config.py (server-side param)

Coord = Annotated[float, Field(ge=0.0, le=1.0)]      # clamped range enforced on validate
MAX_PTS_PER_MSG = 256                                 # oversized-payload guard for draw appends


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def quantize(x: float, bits: int = None) -> float:
    """Snap a normalized coord to a 2**bits grid; round-trips within one step."""
    bits = settings.quant_bits if bits is None else bits
    levels = (1 << bits) - 1
    return round(_clamp01(x) * levels) / levels


class CursorMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cursor"]
    p: tuple[Coord, Coord]
    v: tuple[float, float]
    t: float
    kf: Optional[bool] = None
    name: Optional[str] = Field(default=None, max_length=64)
    color: Optional[str] = Field(default=None, max_length=16)

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v):
        if v is None:
            return v
        v = v.replace("<", "").replace(">", "")
        max_len = settings.max_display_name_len
        return v[:max_len] if len(v) > max_len else v

    @field_validator("p")
    @classmethod
    def _q(cls, p):
        return (quantize(p[0]), quantize(p[1]))


class CursorLeaveMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cursor_leave"]


class DrawMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["draw"]
    seq: int = Field(ge=0)
    pts: list[tuple[Coord, Coord]] = Field(max_length=MAX_PTS_PER_MSG)

    @field_validator("pts")
    @classmethod
    def _q(cls, pts):
        return [(quantize(x), quantize(y)) for (x, y) in pts]


class DrawEndMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["draw_end"]
    seq: int = Field(ge=0)


class HeartbeatMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["heartbeat"]


class SetTickMsMsg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["set_tick_ms"]
    value: int = Field(ge=1, le=500)


# Discriminated union dispatched on `type`; parse_inbound returns a model or raises/None.
INBOUND = {
    "cursor": CursorMsg, "cursor_leave": CursorLeaveMsg,
    "draw": DrawMsg, "draw_end": DrawEndMsg, "heartbeat": HeartbeatMsg,
    "set_tick_ms": SetTickMsMsg,
}


def parse_inbound(raw: dict) -> Optional[BaseModel]:
    """Validate a decoded JSON object; return a model, or None to drop the frame."""
    model = INBOUND.get(raw.get("type"))
    if model is None:
        return None
    return model.model_validate(raw)   # raises ValidationError on malformed/oversized

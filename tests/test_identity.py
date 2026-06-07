"""Tests for EphemeralIdentityProvider (reconnect identity reuse)."""
from app.identity import COLORS, EphemeralIdentityProvider


def test_create_mints_fresh_identity():
    p = EphemeralIdentityProvider()
    ident = p.create(None)
    assert ident["user_id"].startswith("u_")
    assert ident["name"]
    assert ident["color"] in COLORS


def test_create_honors_client_user_id_and_color():
    p = EphemeralIdentityProvider()
    ident = p.create("Ada", user_id="u_deadbeef", color="#4a9eed")
    assert ident["user_id"] == "u_deadbeef"
    assert ident["name"] == "Ada"
    assert ident["color"] == "#4a9eed"


def test_create_rejects_invalid_user_id():
    p = EphemeralIdentityProvider()
    ident = p.create("Bob", user_id="not-valid", color="#4a9eed")
    assert ident["user_id"] != "not-valid"
    assert ident["user_id"].startswith("u_")


def test_create_rejects_unknown_color():
    p = EphemeralIdentityProvider()
    ident = p.create("Bob", user_id="u_cafebabe", color="#000000")
    assert ident["user_id"] == "u_cafebabe"
    assert ident["color"] in COLORS

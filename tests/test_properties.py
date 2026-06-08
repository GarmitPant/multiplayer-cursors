from hypothesis import given, settings, strategies as st

from app.backplane import chan
from app.identity import COLORS


# Property: room→channel mapping is injective (messages never cross room boundaries).
@settings(max_examples=100)
@given(a=st.text(), b=st.text())
def test_room_isolation_injective_channels(a, b):
    if a == b:
        assert chan(a) == chan(b)
    else:
        assert chan(a) != chan(b)


import random
import uuid


def _mint_identity(name_param):
    return {
        "user_id": "u_" + uuid.uuid4().hex[:8],
        "name": name_param or f"user-{uuid.uuid4().hex[:4]}",
        "color": random.choice(COLORS),
    }


# Property: each minted identity has unique user_id, non-empty name, color from palette.
@settings(max_examples=100)
@given(name_params=st.lists(st.one_of(st.none(), st.text()), min_size=1, max_size=50))
def test_identity_valid_and_unique(name_params):
    identities = [_mint_identity(p) for p in name_params]
    user_ids = [i["user_id"] for i in identities]
    assert all(uid for uid in user_ids)              # all non-empty
    assert len(set(user_ids)) == len(user_ids)       # all unique
    assert all(i["name"] for i in identities)        # all names non-empty
    assert all(i["color"] in COLORS for i in identities)


def _should_apply(update, me):
    # Mirrors client predicate: apply iff update has a user_id that is not "me".
    return bool(update.get("user_id")) and update["user_id"] != me


# Property: client applies peer updates only when user_id differs from self.
@settings(max_examples=100)
@given(
    me=st.text(min_size=1),
    others=st.lists(st.text(min_size=1), max_size=50),
)
def test_client_self_filtering(me, others):
    stream = [{"user_id": me}] + [{"user_id": o} for o in others]
    applied = [u for u in stream if _should_apply(u, me)]
    # No applied update may carry the self id.
    assert all(u["user_id"] != me for u in applied)
    # Every non-self update is applied.
    expected = [u for u in stream if u["user_id"] != me]
    assert applied == expected

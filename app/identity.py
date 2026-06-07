"""IdentityProvider seam — EphemeralIdentityProvider mints guest identities on connect."""
import random
import re
import uuid

COLORS = ["#4a9eed", "#22c55e", "#f59e0b", "#ef4444",
          "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]

USER_ID_RE = re.compile(r"^u_[0-9a-f]{8}$")


class EphemeralIdentityProvider:
    """Mint ephemeral guest identity; JWT verification would be a drop-in alternative."""

    def __init__(self, colors: list[str] | None = None) -> None:
        self.colors = colors or COLORS

    def create(
        self,
        name: str | None,
        *,
        user_id: str | None = None,
        color: str | None = None,
    ) -> dict:
        if user_id and USER_ID_RE.match(user_id):
            uid = user_id
        else:
            uid = "u_" + uuid.uuid4().hex[:8]

        nm = (name or "").strip() or f"user-{uuid.uuid4().hex[:4]}"

        if color and color in self.colors:
            col = color
        else:
            col = random.choice(self.colors)

        return {"user_id": uid, "name": nm, "color": col}

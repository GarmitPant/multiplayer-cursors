"""IdentityProvider seam — EphemeralIdentityProvider mints guest identities on connect."""
import random
import uuid

COLORS = ["#4a9eed", "#22c55e", "#f59e0b", "#ef4444",
          "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]


class EphemeralIdentityProvider:
    """Mint ephemeral guest identity; JWT verification would be a drop-in alternative."""

    def __init__(self, colors: list[str] | None = None) -> None:
        self.colors = colors or COLORS

    def create(self, name: str | None) -> dict:
        return {
            "user_id": "u_" + uuid.uuid4().hex[:8],
            "name": name or f"user-{uuid.uuid4().hex[:4]}",
            "color": random.choice(self.colors),
        }

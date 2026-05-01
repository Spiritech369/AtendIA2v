from datetime import datetime, timedelta, timezone

import jwt

from atendia.config import get_settings


def _secret() -> str:
    """WebSocket auth secret. For Phase 2, reuse Meta app secret. In production,
    use a dedicated env var (ATENDIA_V2_WS_AUTH_SECRET)."""
    settings = get_settings()
    return settings.meta_app_secret or "dev-only-fallback"


def issue_token(*, tenant_id: str, ttl_seconds: int = 3600) -> str:
    """Issue a short-TTL JWT scoped to a single tenant."""
    payload = {
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token: str) -> str:
    """Decode a JWT and return the tenant_id. Raises on invalid/expired tokens."""
    payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    return payload["tenant_id"]

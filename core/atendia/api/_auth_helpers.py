"""Operator session auth helpers (Phase 4).

Separate from `realtime/auth.py` (which issues short-TTL WebSocket tokens
scoped to a single tenant via the Meta app secret). The operator session
is HS256 JWT with `auth_session_secret`, carries role + tenant_id claims,
and lives in an httpOnly cookie.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import bcrypt
import jwt
from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from atendia.config import get_settings

# Pre-computed cost-12 bcrypt of an unguessable random string. Used by login()
# to keep timing constant when an email doesn't exist or its hash is NULL —
# without this, a missing-user 401 returns in <1ms but a real-user 401 takes
# ~250ms, leaking which emails are registered. See review HIGH-2.
_DUMMY_HASH: str = bcrypt.hashpw(
    secrets.token_bytes(32), bcrypt.gensalt(rounds=12)
).decode("utf-8")

SESSION_COOKIE = "atendia_session"
CSRF_COOKIE = "atendia_csrf"
JWT_ALGORITHM = "HS256"

Role = Literal["operator", "tenant_admin", "superadmin"]


class AuthUser(BaseModel):
    """Decoded session claims. `tenant_id` is None for superadmins."""

    user_id: UUID
    tenant_id: UUID | None
    role: Role
    email: str
    jti: str | None = None


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def issue_jwt(*, user_id: UUID, tenant_id: UUID | None, role: Role, email: str) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "role": role,
        "email": email,
        "jti": secrets.token_urlsafe(24),
        "exp": datetime.now(UTC) + timedelta(seconds=settings.auth_session_ttl_s),
    }
    return jwt.encode(payload, settings.auth_session_secret, algorithm=JWT_ALGORITHM)


def _revocation_key(jti: str) -> str:
    return f"auth:revoked:{jti}"


def _is_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    try:
        from redis import Redis

        client = Redis.from_url(get_settings().redis_url, socket_timeout=0.2)
        try:
            return bool(client.exists(_revocation_key(jti)))
        finally:
            client.close()
    except Exception:
        return False


def revoke_jwt(token: str) -> bool:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.auth_session_secret,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError:
        return False
    jti = claims.get("jti")
    exp = claims.get("exp")
    if not jti or not exp:
        return False
    ttl = max(1, int(exp) - int(datetime.now(UTC).timestamp()))
    try:
        from redis import Redis

        client = Redis.from_url(settings.redis_url, socket_timeout=0.2)
        try:
            client.set(_revocation_key(str(jti)), "1", ex=ttl)
            return True
        finally:
            client.close()
    except Exception:
        return False


def decode_jwt(token: str, *, check_revocation: bool = True) -> AuthUser:
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.auth_session_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session") from e
    if check_revocation and _is_revoked(claims.get("jti")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session revoked")
    return AuthUser(
        user_id=UUID(claims["sub"]),
        tenant_id=UUID(claims["tid"]) if claims.get("tid") else None,
        role=claims["role"],
        email=claims["email"],
        jti=claims.get("jti"),
    )


def get_current_user(request: Request) -> AuthUser:
    """Read the session cookie and decode it. Raises 401 if missing/invalid."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session cookie")
    return decode_jwt(token)


def new_csrf_token() -> str:
    """Random token returned in body + set as readable cookie. The CSRF
    middleware (Phase 4 T4) compares header vs cookie on unsafe methods."""
    return secrets.token_urlsafe(32)


def constant_time_compare(a: str, b: str) -> bool:
    """Wrapper around `secrets.compare_digest` with str→bytes coercion. Used
    by the CSRF middleware to avoid even theoretical timing leaks against the
    short-lived per-session token."""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def dummy_password_check() -> None:
    """Run a bcrypt verify against a throwaway hash so a missing-user login
    response takes the same wall-clock time as a real-user 401. See HIGH-2
    in the Block A review."""
    bcrypt.checkpw(b"unguessable-placeholder", _DUMMY_HASH.encode("utf-8"))


_DEV_FALLBACK_PREFIX = "dev-only-"


def assert_prod_secret_safety() -> None:
    """Refuse to boot if the operator session secret is the dev fallback
    AND the cookie is being marked Secure (which only makes sense behind
    TLS, i.e. production). This catches the deploy-with-default-secret
    footgun called out as HIGH-1 in the Block A review.

    Called from `main.py`'s lifespan startup."""
    settings = get_settings()
    if settings.auth_cookie_secure and settings.auth_session_secret.startswith(
        _DEV_FALLBACK_PREFIX
    ):
        raise RuntimeError(
            "ATENDIA_V2_AUTH_SESSION_SECRET still uses the dev fallback while "
            "ATENDIA_V2_AUTH_COOKIE_SECURE=true. Set a real 32+ byte secret "
            "before deploying."
        )

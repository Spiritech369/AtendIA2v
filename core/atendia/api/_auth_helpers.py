"""Operator session auth helpers (Phase 4).

Separate from `realtime/auth.py` (which issues short-TTL WebSocket tokens
scoped to a single tenant via the Meta app secret). The operator session
is HS256 JWT with `auth_session_secret`, carries role + tenant_id claims,
and lives in an httpOnly cookie.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import bcrypt
import jwt
from fastapi import HTTPException, Request, status
from pydantic import BaseModel

from atendia.config import get_settings

SESSION_COOKIE = "atendia_session"
CSRF_COOKIE = "atendia_csrf"
JWT_ALGORITHM = "HS256"

Role = Literal["operator", "superadmin"]


class AuthUser(BaseModel):
    """Decoded session claims. `tenant_id` is None for superadmins."""

    user_id: UUID
    tenant_id: UUID | None
    role: Role
    email: str


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
        "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.auth_session_ttl_s),
    }
    return jwt.encode(payload, settings.auth_session_secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> AuthUser:
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.auth_session_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session") from e
    return AuthUser(
        user_id=UUID(claims["sub"]),
        tenant_id=UUID(claims["tid"]) if claims.get("tid") else None,
        role=claims["role"],
        email=claims["email"],
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
    import secrets

    return secrets.token_urlsafe(32)

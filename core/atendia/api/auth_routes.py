"""Operator session auth routes (Phase 4).

POST /api/v1/auth/login    — email + password → sets httpOnly session cookie
                              + returns CSRF token in body (also set as readable cookie)
POST /api/v1/auth/logout   — clears both cookies
POST /api/v1/auth/refresh  — rotates session cookie if current is valid
GET  /api/v1/auth/me       — returns current user claims
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AuthUser,
    Role,
    decode_jwt,
    dummy_password_check,
    get_current_user,
    issue_jwt,
    new_csrf_token,
    revoke_jwt,
    verify_password,
)
from atendia.config import get_settings
from atendia.db.models.tenant import TenantUser
from atendia.db.session import get_db_session

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    role: Role
    email: str


class LoginResponse(BaseModel):
    csrf_token: str
    user: UserResponse


def _set_session_cookies(response: Response, *, jwt_token: str, csrf: str) -> None:
    settings = get_settings()
    # SameSite=Lax (not Strict) so the operator can follow a deep link from
    # email (e.g., "review handoff X") and arrive logged in. CSRF risk is
    # closed by the double-submit middleware (_csrf.py), not by SameSite.
    # Do NOT tighten to Strict without first updating the email-link flow.
    response.set_cookie(
        SESSION_COOKIE,
        jwt_token,
        max_age=settings.auth_session_ttl_s,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.auth_session_ttl_s,
        httponly=False,  # frontend reads this and echoes in X-CSRF-Token header
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    result = await session.execute(
        select(TenantUser).where(TenantUser.email == body.email).limit(1)
    )
    user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        # Run bcrypt against a dummy hash so the 401 returns at roughly the
        # same wall-clock time as a real-user 401 (HIGH-2 in the Block A
        # review — prevents email enumeration via response timing).
        dummy_password_check()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    role = user.role if user.role in ("operator", "tenant_admin", "superadmin") else "operator"
    # Always carry the user's home tenant_id in the JWT — including superadmin.
    # Before sesión 6 superadmin tokens were minted with ``tenant_id=None`` and
    # ``current_tenant_id`` required ``?tid=`` on every request, which the
    # frontend doesn't pass — so list_conversations 400'd. Now the dep uses
    # ``tid`` when explicitly passed (superadmin can still switch tenants),
    # otherwise falls back to the home tenant from the JWT.
    tenant_id = user.tenant_id
    token = issue_jwt(user_id=user.id, tenant_id=tenant_id, role=role, email=user.email)
    csrf = new_csrf_token()
    _set_session_cookies(response, jwt_token=token, csrf=csrf)

    return LoginResponse(
        csrf_token=csrf,
        user=UserResponse(id=user.id, tenant_id=tenant_id, role=role, email=user.email),
    )


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_jwt(token)
    _clear_session_cookies(response)
    return {"ok": True}


@router.post("/refresh", response_model=LoginResponse)
async def refresh(request: Request, response: Response) -> LoginResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session cookie")
    user = decode_jwt(token)
    new_token = issue_jwt(
        user_id=user.user_id, tenant_id=user.tenant_id, role=user.role, email=user.email
    )
    csrf = new_csrf_token()
    _set_session_cookies(response, jwt_token=new_token, csrf=csrf)
    revoke_jwt(token)
    return LoginResponse(
        csrf_token=csrf,
        user=UserResponse(
            id=user.user_id, tenant_id=user.tenant_id, role=user.role, email=user.email
        ),
    )


@router.get("/me", response_model=UserResponse)
async def me(user: AuthUser = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.user_id, tenant_id=user.tenant_id, role=user.role, email=user.email)

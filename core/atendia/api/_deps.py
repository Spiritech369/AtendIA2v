"""FastAPI dependency layer for the operator dashboard API (Phase 4).

Three building blocks:

* `current_user` — reads the httpOnly session cookie, returns AuthUser.
* `current_tenant_id` — resolves which tenant a request applies to:
    - operator → forced to user.tenant_id (JWT, not query — prevents
      a curious operator from poking at other tenants' rows).
    - superadmin → must pass `?tid=...` explicitly.
* `require_superadmin` — gate for `/api/v1/admin/*` style routes.
* `require_tenant_admin` — gate for tenant config/admin writes.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status

from atendia.api._auth_helpers import AuthUser, get_current_user

# Re-export for convenience: routes can `Depends(current_user)`.
current_user = get_current_user


async def current_tenant_id(
    user: AuthUser = Depends(current_user),
    tid: UUID | None = Query(default=None, description="Override (superadmin only)"),
) -> UUID:
    """Resolve the tenant the request applies to.

    - operator / tenant_admin: pinned to ``user.tenant_id`` from the JWT —
      the ``?tid=`` query param is ignored so a curious operator can't poke
      at other tenants by editing the URL.
    - superadmin: ``?tid=`` overrides; if absent, falls back to
      ``user.tenant_id`` (their home tenant). The previous behaviour was to
      400 when ``tid`` was missing, which broke the SPA on every
      conversation-list load (sesión 6 fix).
    """
    if user.role in ("operator", "tenant_admin"):
        if user.tenant_id is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "operator session missing tenant_id"
            )
        return user.tenant_id
    if user.role == "superadmin":
        if tid is not None:
            return tid
        if user.tenant_id is not None:
            return user.tenant_id
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "superadmin has no home tenant — pass ?tid=<uuid> to scope",
        )
    raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown role")


async def require_superadmin(
    user: AuthUser = Depends(current_user),
) -> AuthUser:
    if user.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin only")
    return user


async def require_tenant_admin(
    user: AuthUser = Depends(current_user),
) -> AuthUser:
    if user.role not in ("tenant_admin", "superadmin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant admin only")
    return user

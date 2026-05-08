"""FastAPI dependency layer for the operator dashboard API (Phase 4).

Three building blocks:

* `current_user` — reads the httpOnly session cookie, returns AuthUser.
* `current_tenant_id` — resolves which tenant a request applies to:
    - operator → forced to user.tenant_id (JWT, not query — prevents
      a curious operator from poking at other tenants' rows).
    - superadmin → must pass `?tid=...` explicitly.
* `require_superadmin` — gate for `/api/v1/admin/*` style routes.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status

from atendia.api._auth_helpers import AuthUser, get_current_user

# Re-export for convenience: routes can `Depends(current_user)`.
current_user = get_current_user


async def current_tenant_id(
    user: AuthUser = Depends(current_user),
    tid: UUID | None = Query(default=None, description="Required for superadmin"),
) -> UUID:
    if user.role == "operator":
        if user.tenant_id is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "operator session missing tenant_id"
            )
        return user.tenant_id
    if user.role == "superadmin":
        if tid is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "tid query param required for superadmin endpoints",
            )
        return tid
    raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown role")


async def require_superadmin(
    user: AuthUser = Depends(current_user),
) -> AuthUser:
    if user.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin only")
    return user

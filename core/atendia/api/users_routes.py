"""Operator dashboard — user management (Phase 4 T47, Block I).

Routes:
* `GET    /api/v1/users` — list. Operators see their tenant only.
  Superadmins see all (or filter by ?tid=).
* `POST   /api/v1/users` — create.
* `PATCH  /api/v1/users/:id` — update (email, role, password optional).
* `DELETE /api/v1/users/:id` — soft via 204.

Roles: `operator` | `tenant_admin` | `superadmin`. Tenant admins can manage
users inside their tenant; superadmins can manage every tenant.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser, hash_password
from atendia.api._deps import current_user, require_superadmin
from atendia.db.models.tenant import TenantUser
from atendia.db.session import get_db_session

router = APIRouter()
TENANT_ROLES = {"operator", "tenant_admin"}
ALL_ROLES = TENANT_ROLES | {"superadmin"}


class UserItem(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    role: str
    has_password: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    role: str = "operator"
    password: str
    tenant_id: UUID | None = None  # superadmin can create users in any tenant

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        if value not in ALL_ROLES:
            raise ValueError("invalid role")
        return value


class UserPatch(BaseModel):
    email: EmailStr | None = None
    role: str | None = None
    password: str | None = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str | None) -> str | None:
        if value is not None and value not in ALL_ROLES:
            raise ValueError("invalid role")
        return value


def _to_item(u: TenantUser) -> UserItem:
    return UserItem(
        id=u.id,
        tenant_id=u.tenant_id,
        email=u.email,
        role=u.role,
        has_password=u.password_hash is not None,
        created_at=u.created_at,
    )


@router.get("", response_model=list[UserItem])
async def list_users(
    user: AuthUser = Depends(current_user),
    tid: UUID | None = Query(None, description="Filter for superadmin"),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserItem]:
    if user.role == "superadmin":
        stmt = select(TenantUser)
        if tid is not None:
            stmt = stmt.where(TenantUser.tenant_id == tid)
    else:
        # Operator / tenant_admin see only their own tenant.
        if user.tenant_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "user has no tenant")
        stmt = select(TenantUser).where(TenantUser.tenant_id == user.tenant_id)
    rows = (await session.execute(stmt.order_by(TenantUser.created_at.desc()))).scalars().all()
    return [_to_item(u) for u in rows]


@router.post("", response_model=UserItem)
async def create_user(
    body: UserCreate,
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserItem:
    # Resolve target tenant.
    if user.role == "superadmin":
        target_tenant = body.tenant_id
        if target_tenant is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "superadmin must specify tenant_id when creating a user",
            )
    elif user.role == "tenant_admin":
        if user.tenant_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "user has no tenant")
        target_tenant = user.tenant_id
        # An operator/admin cannot create a superadmin.
        if body.role == "superadmin":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "only superadmin can create superadmin users",
            )
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant admin only")

    new_user = TenantUser(
        tenant_id=target_tenant,
        email=body.email,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    return _to_item(new_user)


async def _load_or_404(
    session: AsyncSession, user_id: UUID, *, current: AuthUser
) -> TenantUser:
    u = (
        await session.execute(select(TenantUser).where(TenantUser.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    # RBAC: operator can only act on users in their own tenant.
    if current.role != "superadmin" and u.tenant_id != current.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return u


@router.patch("/{user_id}", response_model=UserItem)
async def patch_user(
    user_id: UUID,
    body: UserPatch,
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserItem:
    target = await _load_or_404(session, user_id, current=user)
    if user.role == "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant admin only")
    values: dict = {}
    if body.email is not None:
        values["email"] = body.email
    if body.role is not None:
        if user.role != "superadmin" and body.role == "superadmin":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "only superadmin can grant superadmin"
            )
        values["role"] = body.role
    if body.password is not None:
        values["password_hash"] = hash_password(body.password)
    if values:
        await session.execute(
            update(TenantUser).where(TenantUser.id == user_id).values(**values)
        )
        await session.commit()
        await session.refresh(target)
    return _to_item(target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    target = await _load_or_404(session, user_id, current=user)
    if user.role == "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant admin only")
    if target.id == user.user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete yourself")
    await session.execute(delete(TenantUser).where(TenantUser.id == user_id))
    await session.commit()


# ---- Superadmin-only endpoint sketch (future use) ----


@router.get("/_admin/all", response_model=list[UserItem])
async def admin_list_all(
    _user: AuthUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserItem]:
    """Belt+suspenders for explicit superadmin-only listing without query
    param ambiguity. Same shape as /users but rejects 403 for operators."""
    rows = (await session.execute(select(TenantUser))).scalars().all()
    return [_to_item(u) for u in rows]

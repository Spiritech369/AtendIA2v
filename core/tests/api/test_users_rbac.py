"""RBAC tests for tenant user management."""
from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings


def _seed_user(tid: str, role: str = "operator") -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, :r, :h) RETURNING id"
                    ),
                    {
                        "t": tid,
                        "e": f"users_rbac_{uuid4().hex[:8]}@dinamo.com",
                        "r": role,
                        "h": hash_password("test-password-123"),
                    },
                )
            ).scalar()
        await engine.dispose()
        return str(uid)

    return asyncio.run(_do())


def test_operator_cannot_create_user(client_operator):
    resp = client_operator.post(
        "/api/v1/users",
        json={
            "email": f"new_{uuid4().hex[:8]}@dinamo.com",
            "role": "operator",
            "password": "test-password-123",
        },
    )
    assert resp.status_code == 403


def test_tenant_admin_can_create_operator(client_tenant_admin):
    email = f"new_{uuid4().hex[:8]}@dinamo.com"
    resp = client_tenant_admin.post(
        "/api/v1/users",
        json={
            "email": email,
            "role": "operator",
            "password": "test-password-123",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "operator"
    assert body["tenant_id"] == client_tenant_admin.tenant_id


def test_tenant_admin_cannot_create_superadmin(client_tenant_admin):
    resp = client_tenant_admin.post(
        "/api/v1/users",
        json={
            "email": f"new_{uuid4().hex[:8]}@dinamo.com",
            "role": "superadmin",
            "password": "test-password-123",
        },
    )
    assert resp.status_code == 403


def test_operator_cannot_patch_or_delete_user(client_operator):
    target_id = _seed_user(client_operator.tenant_id)

    patch = client_operator.patch(
        f"/api/v1/users/{target_id}",
        json={"role": "tenant_admin"},
    )
    delete = client_operator.delete(f"/api/v1/users/{target_id}")

    assert patch.status_code == 403
    assert delete.status_code == 403


def test_tenant_admin_can_patch_and_delete_user(client_tenant_admin):
    target_id = _seed_user(client_tenant_admin.tenant_id)

    patch = client_tenant_admin.patch(
        f"/api/v1/users/{target_id}",
        json={"role": "tenant_admin"},
    )
    delete = client_tenant_admin.delete(f"/api/v1/users/{target_id}")

    assert patch.status_code == 200, patch.text
    assert patch.json()["role"] == "tenant_admin"
    assert delete.status_code == 204

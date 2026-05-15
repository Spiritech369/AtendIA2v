"""Phase 4 T3 — tests for the API dependency layer.

Each test mounts a tiny throwaway router that uses one dep, then drives
it through the real auth flow via the shared client_operator /
client_superadmin fixtures.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import (
    current_tenant_id,
    current_user,
    require_superadmin,
    require_tenant_admin,
)
from atendia.api.auth_routes import router as auth_router


def _make_test_app() -> FastAPI:
    """Fresh FastAPI app with auth + the three deps wired to ping endpoints."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth")

    @app.get("/_ping/me")
    async def _ping_me(user: AuthUser = Depends(current_user)) -> dict:
        return {"user_id": str(user.user_id), "role": user.role}

    @app.get("/_ping/tenant")
    async def _ping_tenant(tid: UUID = Depends(current_tenant_id)) -> dict:
        return {"tid": str(tid)}

    @app.get("/_ping/admin")
    async def _ping_admin(user: AuthUser = Depends(require_superadmin)) -> dict:
        return {"user_id": str(user.user_id)}

    @app.get("/_ping/tenant-admin")
    async def _ping_tenant_admin(user: AuthUser = Depends(require_tenant_admin)) -> dict:
        return {"user_id": str(user.user_id), "role": user.role}

    return app


def _login(client: TestClient, email: str, password: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def test_current_user_returns_401_without_cookie():
    app = _make_test_app()
    client = TestClient(app)
    assert client.get("/_ping/me").status_code == 401


def test_current_tenant_id_forces_jwt_value_for_operator(operator_seed):
    tid, _, email, plain = operator_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)

    # operator: query tid is IGNORED, JWT tenant_id wins
    other_tid = str(uuid4())
    resp = client.get(f"/_ping/tenant?tid={other_tid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["tid"] == tid


def test_superadmin_falls_back_to_home_tenant_without_query_param(superadmin_seed):
    """Sesión 6 fix: superadmin no longer 400s when ``?tid=`` is omitted.
    The dep falls back to the user's home tenant from the JWT, so the SPA
    works without a tenant selector. ``?tid=`` still overrides explicitly."""
    home_tid, _, email, plain = superadmin_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)

    # without ?tid= → falls back to JWT home tenant
    resp = client.get("/_ping/tenant")
    assert resp.status_code == 200, resp.text
    assert resp.json()["tid"] == home_tid

    # with ?tid= → overrides
    target = str(uuid4())
    resp = client.get(f"/_ping/tenant?tid={target}")
    assert resp.status_code == 200
    assert resp.json()["tid"] == target


def test_require_superadmin_blocks_operator(operator_seed):
    _, _, email, plain = operator_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)
    assert client.get("/_ping/admin").status_code == 403


def test_require_superadmin_allows_superadmin(superadmin_seed):
    _, uid, email, plain = superadmin_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)
    resp = client.get("/_ping/admin")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == uid


def test_current_tenant_id_forces_jwt_value_for_tenant_admin(tenant_admin_seed):
    tid, _, email, plain = tenant_admin_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)

    other_tid = str(uuid4())
    resp = client.get(f"/_ping/tenant?tid={other_tid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["tid"] == tid


def test_require_tenant_admin_blocks_operator(operator_seed):
    _, _, email, plain = operator_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)
    assert client.get("/_ping/tenant-admin").status_code == 403


def test_require_tenant_admin_allows_tenant_admin(tenant_admin_seed):
    _, uid, email, plain = tenant_admin_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)
    resp = client.get("/_ping/tenant-admin")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": uid, "role": "tenant_admin"}


def test_require_tenant_admin_allows_superadmin(superadmin_seed):
    _, uid, email, plain = superadmin_seed
    client = TestClient(_make_test_app())
    _login(client, email, plain)
    resp = client.get("/_ping/tenant-admin")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": uid, "role": "superadmin"}

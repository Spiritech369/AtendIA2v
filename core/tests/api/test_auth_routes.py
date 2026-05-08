"""Phase 4 T2 — operator session auth route tests.

Covers: login_ok, login_bad_pwd, logout_clears_cookie, me_returns_claims.
"""
import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    hash_password,
)
from atendia.config import get_settings
from atendia.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def operator_user():
    """Seed a tenant + operator user with a known bcrypt password.

    Yields (tenant_id, user_id, email, plain_password). Cleans up after.
    """
    email = f"phase4_t2_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _setup() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenants (name) VALUES (:n) RETURNING id"
                    ),
                    {"n": f"phase4_t2_tenant_{uuid4().hex[:8]}"},
                )
            ).scalar()
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, 'operator', :h) RETURNING id"
                    ),
                    {"t": tid, "e": email, "h": hashed},
                )
            ).scalar()
        await engine.dispose()
        return str(tid), str(uid)

    async def _cleanup(tid: str) -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    tid, uid = asyncio.run(_setup())
    yield tid, uid, email, plain
    asyncio.run(_cleanup(tid))


def test_login_returns_jwt_cookie_and_csrf_token(client, operator_user):
    tid, uid, email, plain = operator_user
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": plain})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["csrf_token"]
    assert body["user"]["role"] == "operator"
    assert body["user"]["tenant_id"] == tid
    assert body["user"]["email"] == email
    assert body["user"]["id"] == uid

    # httpOnly session cookie set
    assert SESSION_COOKIE in resp.cookies
    # CSRF cookie set (NOT httpOnly so frontend JS can read it)
    assert CSRF_COOKIE in resp.cookies
    assert resp.cookies[CSRF_COOKIE] == body["csrf_token"]


def test_login_with_bad_password_returns_401(client, operator_user):
    _, _, email, _ = operator_user
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert SESSION_COOKIE not in resp.cookies


def test_logout_clears_cookie(client, operator_user):
    _, _, email, plain = operator_user
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 200
    # Set-Cookie header should expire the session cookie. TestClient surfaces
    # cookies with empty values when deleted via response.delete_cookie.
    set_cookie_headers = logout.headers.get_list("set-cookie")
    assert any(
        SESSION_COOKIE in h and ("Max-Age=0" in h or "expires=" in h.lower())
        for h in set_cookie_headers
    ), set_cookie_headers


def test_me_returns_claims(client, operator_user):
    tid, uid, email, plain = operator_user
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert login.status_code == 200

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["id"] == uid
    assert body["tenant_id"] == tid
    assert body["role"] == "operator"
    assert body["email"] == email


def test_me_without_cookie_returns_401(client):
    fresh = TestClient(app)
    resp = fresh.get("/api/v1/auth/me")
    assert resp.status_code == 401

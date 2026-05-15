"""Shared fixtures for `tests/api/*` (Phase 4).

* `client` — bare TestClient against the FastAPI app.
* `operator_seed` / `superadmin_seed` — async-seeded users with bcrypt hashes,
  yielding (tenant_id, user_id, email, plain_password). Cleaned up after.
* `client_operator` / `client_superadmin` — TestClient already logged in as
  the corresponding role; cookies are populated after the login() call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.main import app


def _seed_user(role: str) -> tuple[str, str, str, str]:
    """Synchronous wrapper around an async seed. Returns (tid, uid, email, pwd)."""
    email = f"phase4_t3_{role}_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t3_tenant_{uuid4().hex[:8]}"},
                )
            ).scalar()
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, :r, :h) RETURNING id"
                    ),
                    {"t": tid, "e": email, "r": role, "h": hashed},
                )
            ).scalar()
        await engine.dispose()
        return str(tid), str(uid)

    tid, uid = asyncio.run(_do())
    return tid, uid, email, plain


def _cleanup_tenant(tid: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    asyncio.run(_do())


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def operator_seed() -> Iterator[tuple[str, str, str, str]]:
    tid, uid, email, plain = _seed_user("operator")
    yield tid, uid, email, plain
    _cleanup_tenant(tid)


@pytest.fixture
def superadmin_seed() -> Iterator[tuple[str, str, str, str]]:
    tid, uid, email, plain = _seed_user("superadmin")
    yield tid, uid, email, plain
    _cleanup_tenant(tid)


@pytest.fixture
def tenant_admin_seed() -> Iterator[tuple[str, str, str, str]]:
    tid, uid, email, plain = _seed_user("tenant_admin")
    yield tid, uid, email, plain
    _cleanup_tenant(tid)


@pytest.fixture
def client_operator(operator_seed) -> Iterator[TestClient]:
    """TestClient with operator session cookie + CSRF header already set."""
    tid, uid, email, plain = operator_seed
    c = TestClient(app)
    resp = c.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200, resp.text
    c.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    c.tenant_id = tid  # type: ignore[attr-defined]  # convenience for assertions
    c.user_id = uid  # type: ignore[attr-defined]
    yield c


@pytest.fixture
def client_tenant_admin(tenant_admin_seed) -> Iterator[TestClient]:
    """TestClient with tenant_admin session cookie + CSRF header already set."""
    tid, uid, email, plain = tenant_admin_seed
    c = TestClient(app)
    resp = c.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200, resp.text
    c.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    c.tenant_id = tid  # type: ignore[attr-defined]
    c.user_id = uid  # type: ignore[attr-defined]
    yield c


@pytest.fixture
def client_superadmin(superadmin_seed) -> Iterator[TestClient]:
    """TestClient with superadmin session cookie + CSRF header already set."""
    tid, uid, email, plain = superadmin_seed
    c = TestClient(app)
    resp = c.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200, resp.text
    c.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    c.home_tenant_id = tid  # type: ignore[attr-defined]
    c.user_id = uid  # type: ignore[attr-defined]
    yield c

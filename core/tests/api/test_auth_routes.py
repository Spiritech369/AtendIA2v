"""Phase 4 T2 — operator session auth route tests.

Covers: login_ok, login_bad_pwd, logout_clears_cookie, me_returns_claims,
me_without_cookie_401, login_unknown_email_constant_time.

Uses the shared `client` and `operator_seed` fixtures from `conftest.py`.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from atendia.api._auth_helpers import CSRF_COOKIE, SESSION_COOKIE
from atendia.main import app


def test_login_returns_jwt_cookie_and_csrf_token(client, operator_seed):
    tid, uid, email, plain = operator_seed
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


def test_login_with_bad_password_returns_401(client, operator_seed):
    _, _, email, _ = operator_seed
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert SESSION_COOKIE not in resp.cookies


def test_logout_clears_cookie(client, operator_seed):
    _, _, email, plain = operator_seed
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 200
    # Starlette emits Max-Age=0 on delete_cookie; assert that specifically.
    set_cookie_headers = logout.headers.get_list("set-cookie")
    assert any(
        SESSION_COOKIE in h and "Max-Age=0" in h for h in set_cookie_headers
    ), set_cookie_headers


def test_me_returns_claims(client, operator_seed):
    tid, uid, email, plain = operator_seed
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert login.status_code == 200

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["id"] == uid
    assert body["tenant_id"] == tid
    assert body["role"] == "operator"
    assert body["email"] == email


def test_me_without_cookie_returns_401():
    fresh = TestClient(app)
    resp = fresh.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_login_unknown_email_runs_dummy_bcrypt(client):
    """HIGH-2 from Block A review: missing-user 401 should not be detectably
    faster than real-user 401. Sanity-bound by lower bound only — we can't
    measure absolute equality, but a missing user without dummy_password_check
    would return in <5ms; with the check it takes ~150ms+."""
    t0 = time.perf_counter()
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-here@dinamo.com", "password": "irrelevant"},
    )
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 401
    # Should take meaningfully longer than a 5ms NotFound. Cost-12 bcrypt is
    # >100ms on modern CPUs; allow generous lower bound for slow CI.
    assert elapsed > 0.05, f"login looked too fast for missing user: {elapsed*1000:.1f}ms"

"""Phase 4 T4 — CSRF middleware tests (double-submit cookie pattern)."""
from __future__ import annotations


def test_login_works_without_csrf(client, operator_seed):
    """`/api/v1/auth/login` is the bootstrap call — no cookie yet to compare."""
    _, _, email, plain = operator_seed
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200, resp.text


def test_post_logout_without_csrf_header_returns_403(client, operator_seed):
    _, _, email, plain = operator_seed
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert login.status_code == 200

    # No X-CSRF-Token header, despite cookie being present from login
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 403
    assert "csrf" in resp.json()["detail"].lower()


def test_post_logout_with_matching_csrf_header_succeeds(client, operator_seed):
    _, _, email, plain = operator_seed
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    csrf = login.json()["csrf_token"]

    resp = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200


def test_post_with_mismatched_csrf_token_returns_403(client, operator_seed):
    _, _, email, plain = operator_seed
    client.post("/api/v1/auth/login", json={"email": email, "password": plain})

    resp = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong-token-totally-different"}
    )
    assert resp.status_code == 403


def test_get_endpoint_works_without_csrf(client_operator):
    """GET is a safe method — no CSRF check.

    Strip the auto-set CSRF header to prove the dep on safe-methods exemption.
    """
    client_operator.headers.pop("X-CSRF-Token", None)
    resp = client_operator.get("/api/v1/auth/me")
    assert resp.status_code == 200


def test_post_refresh_requires_csrf(client, operator_seed):
    _, _, email, plain = operator_seed
    login = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    csrf = login.json()["csrf_token"]

    # Without header
    no_header = client.post("/api/v1/auth/refresh")
    assert no_header.status_code == 403

    # With matching header
    ok = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200

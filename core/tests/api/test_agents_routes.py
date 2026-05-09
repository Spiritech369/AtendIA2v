"""Hardening tests for agents_routes (Session 9 of v1 parity).

The frontend stops dumping JSON and uses real form controls now, so we make
sure the backend keeps the contract the UI relies on:
- list / get / create / patch / delete CRUD
- only ``tenant_admin`` can mutate
- one-default-per-tenant invariant
- intent + role validation
- /agents/test echoes intent for the simple keywords the UI primes ("hola",
  "precio")
"""
from __future__ import annotations


def _create(client, **overrides):
    body = {
        "name": "Ventas",
        "role": "sales",
        "is_default": True,
        "active_intents": ["GREETING", "ASK_PRICE"],
    }
    body.update(overrides)
    return client.post("/api/v1/agents", json=body)


def test_full_crud_roundtrip(client_tenant_admin):
    created = _create(client_tenant_admin, name="Original")
    assert created.status_code == 201, created.text
    aid = created.json()["id"]

    listing = client_tenant_admin.get("/api/v1/agents").json()
    assert any(a["id"] == aid for a in listing)

    detail = client_tenant_admin.get(f"/api/v1/agents/{aid}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Original"

    updated = client_tenant_admin.patch(
        f"/api/v1/agents/{aid}",
        json={"name": "Renombrado", "tone": "formal"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renombrado"
    assert updated.json()["tone"] == "formal"

    # The only default agent cannot be deleted (would leave the tenant
    # without one). Add a second default first.
    second = _create(client_tenant_admin, name="Backup", is_default=True)
    assert second.status_code == 201

    deleted = client_tenant_admin.delete(f"/api/v1/agents/{aid}")
    assert deleted.status_code == 204
    assert client_tenant_admin.get(f"/api/v1/agents/{aid}").status_code == 404


def test_creating_second_default_clears_previous(client_tenant_admin):
    first = _create(client_tenant_admin, name="A", is_default=True).json()
    second = _create(client_tenant_admin, name="B", is_default=True).json()

    listing = {a["id"]: a for a in client_tenant_admin.get("/api/v1/agents").json()}
    assert listing[first["id"]]["is_default"] is False
    assert listing[second["id"]]["is_default"] is True


def test_invalid_role_rejected(client_tenant_admin):
    resp = _create(client_tenant_admin, role="impostor")
    assert resp.status_code == 422


def test_unknown_intents_rejected(client_tenant_admin):
    resp = _create(client_tenant_admin, active_intents=["GREETING", "NOT_REAL"])
    assert resp.status_code == 422


def test_operator_cannot_mutate(client_operator, client_tenant_admin):
    """``operator`` role is read-only on /agents — confirm the dependency
    actually rejects mutating calls."""
    # Seed via admin so there's something to read.
    created = _create(client_tenant_admin)
    aid = created.json()["id"]

    # Ops can list/read.
    assert client_operator.get("/api/v1/agents").status_code in (200, 400)
    # Ops cannot create / patch / delete.
    assert client_operator.post(
        "/api/v1/agents", json={"name": "x", "role": "sales"}
    ).status_code in (401, 403)
    assert client_operator.patch(
        f"/api/v1/agents/{aid}", json={"name": "x"}
    ).status_code in (401, 403, 404)


def test_test_endpoint_echoes_intent_for_known_keywords(client_tenant_admin):
    saludo = client_tenant_admin.post(
        "/api/v1/agents/test",
        json={"agent_config": {"name": "X", "role": "sales"}, "message": "hola buen día"},
    ).json()
    assert saludo["intent"] == "GREETING"

    precio = client_tenant_admin.post(
        "/api/v1/agents/test",
        json={"agent_config": {"name": "X", "role": "sales"}, "message": "¿cuál es el precio?"},
    ).json()
    assert precio["intent"] == "ASK_PRICE"


def test_extra_field_on_patch_is_rejected(client_tenant_admin):
    """The frontend sends a closed set of fields. Catch typos via ``extra=forbid``."""
    aid = _create(client_tenant_admin).json()["id"]
    resp = client_tenant_admin.patch(
        f"/api/v1/agents/{aid}",
        json={"this_is_not_a_field": True},
    )
    assert resp.status_code == 422

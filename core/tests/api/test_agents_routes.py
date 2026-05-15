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
    assert client_operator.patch(f"/api/v1/agents/{aid}", json={"name": "x"}).status_code in (
        401,
        403,
        404,
    )


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


# ──────────────────────────────────────────────────────────────────────
# Version history + rollback (A1 — full snapshots).
# ──────────────────────────────────────────────────────────────────────


def _create_publishable(client, **overrides):
    """Create an agent that satisfies _validate_agent_config so /publish
    doesn't 409. The validator requires goal + language + at least one
    guardrail + at least one extraction_field on top of the base fields."""
    body = {
        "name": "Publisher",
        "role": "sales",
        "is_default": True,
        "active_intents": ["GREETING", "ASK_PRICE"],
        "language": "es",
        "goal": "Cerrar ventas con calidez",
        "max_sentences": 3,
    }
    body.update(overrides)
    resp = client.post("/api/v1/agents", json=body)
    assert resp.status_code == 201, resp.text
    aid = resp.json()["id"]
    # Each agent needs at least one guardrail + one extraction_field.
    client.post(
        f"/api/v1/agents/{aid}/guardrails",
        json={
            "severity": "high",
            "name": "No prometer aprobación",
            "rule_text": "Nunca digas que el cliente está aprobado.",
            "allowed_examples": [],
            "forbidden_examples": [],
            "active": True,
            "enforcement_mode": "warn",
        },
    )
    client.post(
        f"/api/v1/agents/{aid}/extraction-fields",
        json={
            "field_key": "nombre",
            "label": "Nombre",
            "type": "text",
            "required": True,
            "confidence_threshold": 0.6,
            "auto_save": True,
            "requires_confirmation": False,
            "source_message_tracking": True,
            "enum_options": [],
        },
    )
    return aid


def test_publish_captures_full_config_snapshot(client_tenant_admin):
    """Each /publish must store a serializable snapshot of the live config
    inside the new version dict so a later rollback can restore it byte-for-byte."""
    aid = _create_publishable(client_tenant_admin, name="VersionedAgent", tone="formal")

    client_tenant_admin.patch(
        f"/api/v1/agents/{aid}",
        json={"system_prompt": "Eres un asistente formal.", "max_sentences": 4},
    )

    resp = client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")
    assert resp.status_code == 200, resp.text
    versions = resp.json()["versions"]
    assert len(versions) >= 1
    snap = versions[0].get("snapshot")
    assert snap, "publish must persist a snapshot for the version it created"
    assert snap["tone"] == "formal"
    assert snap["system_prompt"] == "Eres un asistente formal."
    assert snap["max_sentences"] == 4


def test_rollback_to_specific_version_restores_snapshot(client_tenant_admin):
    """Operator picks an exact version_id from the history → the row's
    config fields are replaced with that version's snapshot."""
    aid = _create_publishable(client_tenant_admin, name="A", tone="formal")

    client_tenant_admin.patch(
        f"/api/v1/agents/{aid}",
        json={"system_prompt": "Versión 1.", "tone": "formal", "max_sentences": 2},
    )
    v1 = client_tenant_admin.post(f"/api/v1/agents/{aid}/publish").json()
    v1_version_id = v1["versions"][0]["id"]

    client_tenant_admin.patch(
        f"/api/v1/agents/{aid}",
        json={"system_prompt": "Versión 2.", "tone": "amigable", "max_sentences": 5},
    )
    v2 = client_tenant_admin.post(f"/api/v1/agents/{aid}/publish").json()
    assert v2["system_prompt"] == "Versión 2."
    assert v2["tone"] == "amigable"

    rolled = client_tenant_admin.post(
        f"/api/v1/agents/{aid}/rollback", json={"version_id": v1_version_id}
    )
    assert rolled.status_code == 200, rolled.text
    body = rolled.json()
    assert body["system_prompt"] == "Versión 1."
    assert body["tone"] == "formal"
    assert body["max_sentences"] == 2


def test_rollback_without_version_id_goes_to_previous(client_tenant_admin):
    """Empty body = roll back to the version just before the current
    head (index 1 in the list — index 0 is the live snapshot)."""
    aid = _create_publishable(client_tenant_admin, name="A")
    client_tenant_admin.patch(f"/api/v1/agents/{aid}", json={"tone": "formal"})
    client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")
    client_tenant_admin.patch(f"/api/v1/agents/{aid}", json={"tone": "amigable"})
    client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")

    rolled = client_tenant_admin.post(f"/api/v1/agents/{aid}/rollback", json={})
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["tone"] == "formal"


def test_rollback_to_missing_version_is_404(client_tenant_admin):
    aid = _create_publishable(client_tenant_admin)
    client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")
    resp = client_tenant_admin.post(f"/api/v1/agents/{aid}/rollback", json={"version_id": "nope"})
    assert resp.status_code == 404


def test_rollback_when_no_prior_version_is_409(client_tenant_admin):
    aid = _create_publishable(client_tenant_admin)
    client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")  # only 1 version exists
    resp = client_tenant_admin.post(f"/api/v1/agents/{aid}/rollback", json={})
    assert resp.status_code == 409


def test_rollback_to_legacy_version_without_snapshot_is_409(client_tenant_admin):
    """Versions published before snapshot persistence have no `snapshot`
    field. The endpoint must refuse the rollback rather than silently
    leaving the live config untouched."""
    aid = _create_publishable(client_tenant_admin)
    # Force-publish twice to produce a head + a previous version, then
    # nuke the prior version's snapshot via DB write to simulate legacy.
    client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")
    client_tenant_admin.patch(f"/api/v1/agents/{aid}", json={"tone": "formal"})
    client_tenant_admin.post(f"/api/v1/agents/{aid}/publish")

    import asyncio

    from sqlalchemy import text as sql_text
    from sqlalchemy.ext.asyncio import create_async_engine

    from atendia.config import get_settings

    async def _wipe_old_snapshot() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                sql_text(
                    "UPDATE agents "
                    "SET ops_config = jsonb_set("
                    "    ops_config, "
                    "    '{versions,1,snapshot}', "
                    "    'null'::jsonb"
                    ") "
                    "WHERE id = :a"
                ),
                {"a": aid},
            )
        await engine.dispose()

    asyncio.run(_wipe_old_snapshot())

    resp = client_tenant_admin.post(f"/api/v1/agents/{aid}/rollback", json={})
    assert resp.status_code == 409, resp.text

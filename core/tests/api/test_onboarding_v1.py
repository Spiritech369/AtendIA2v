from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _db_scalar(sql: str, params: dict | None = None):
    async def _run():
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                return (await conn.execute(text(sql), params or {})).scalar()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _db_execute(sql: str, params: dict | None = None) -> None:
    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params or {})
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _seed_channel(tenant_id: str) -> None:
    _db_execute(
        "INSERT INTO tenant_baileys_config "
        "(tenant_id, enabled, connected_phone, last_status, prefer_over_meta) "
        "VALUES (:t, true, '+5215550000000', 'connected', true) "
        "ON CONFLICT (tenant_id) DO UPDATE SET enabled=true, last_status='connected'",
        {"t": tenant_id},
    )


def _seed_agent(tenant_id: str) -> str:
    return str(
        _db_scalar(
            "INSERT INTO agents (tenant_id, name, status) "
            "VALUES (:t, :n, 'production') RETURNING id",
            {"t": tenant_id, "n": f"onboarding_agent_{uuid4().hex[:8]}"},
        )
    )


def _seed_readiness(tenant_id: str, agent_id: str, *, passed: bool = True) -> None:
    _db_execute(
        "INSERT INTO agent_readiness_eval_results "
        "(id, tenant_id, agent_id, suite_id, score, passed, scenario_count, "
        "failed_scenarios, policy_failures, metadata) "
        "VALUES (:id, :t, :a, 'agent_runtime_v2_minimum_readiness', "
        ":score, :passed, 1, CAST('[]' AS jsonb), CAST('[]' AS jsonb), "
        "CAST('{}' AS jsonb))",
        {
            "id": str(uuid4()),
            "t": tenant_id,
            "a": agent_id,
            "score": 1.0 if passed else 0.0,
            "passed": passed,
        },
    )


def _seed_field(tenant_id: str) -> None:
    _db_execute(
        "INSERT INTO customer_field_definitions "
        "(id, tenant_id, key, label, field_type, field_options, ordering) "
        "VALUES (:id, :t, :k, 'Need', 'text', NULL, 1)",
        {"id": str(uuid4()), "t": tenant_id, "k": f"need_{uuid4().hex[:6]}"},
    )


def _seed_pipeline(tenant_id: str) -> None:
    definition = {"version": 1, "stages": [{"id": "new", "label": "New"}]}
    _db_execute(
        "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
        "VALUES (:t, :v, CAST(:d AS jsonb), true)",
        {
            "t": tenant_id,
            "v": 950000 + uuid4().int % 10000,
            "d": json.dumps(definition),
        },
    )


def _seed_knowledge(tenant_id: str) -> None:
    _db_execute(
        "INSERT INTO knowledge_sources (id, tenant_id, name, type, content_type, status) "
        "VALUES (:id, :t, 'Onboarding source', 'manual', 'general', 'active')",
        {"id": str(uuid4()), "t": tenant_id},
    )


def _set_selected_blueprint(tenant_id: str) -> None:
    _db_execute(
        "INSERT INTO onboarding_states (tenant_id, selected_blueprint_id, current_step) "
        "VALUES (:t, 'beauty_barber_spa', 'test_agent') "
        "ON CONFLICT (tenant_id) DO UPDATE SET selected_blueprint_id='beauty_barber_spa'",
        {"t": tenant_id},
    )


def _seed_other_tenant_state() -> tuple[str, str]:
    async def _run() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"onboarding_other_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_states "
                        "(tenant_id, selected_blueprint_id, current_step) "
                        "VALUES (:t, 'dental_clinic', 'other_step')"
                    ),
                    {"t": tenant_id},
                )
            return str(tenant_id), "dental_clinic"
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _delete_tenant(tenant_id: str) -> None:
    _db_execute("DELETE FROM tenants WHERE id = :t", {"t": tenant_id})


def _blocking_codes(body: dict) -> set[str]:
    return set(body["blocking_codes"])


def test_state_created_for_tenant(client_tenant_admin):
    resp = client_tenant_admin.get("/api/v1/onboarding/state")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == client_tenant_admin.tenant_id
    assert body["current_step"] == "select_blueprint"
    assert body["published"] is False


def test_select_blueprint_updates_state_and_installs_base_config(client_tenant_admin):
    resp = client_tenant_admin.post(
        "/api/v1/onboarding/select-blueprint",
        json={"blueprint_id": "beauty_barber_spa"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"]["selected_blueprint_id"] == "beauty_barber_spa"
    assert body["state"]["agent_configured"] is True
    assert body["state"]["contact_fields_ready"] is True
    assert body["state"]["lifecycle_ready"] is True
    assert body["install_result"]["eval_scenario_ids"]
    assert body["state"]["knowledge_uploaded"] is False
    assert body["state"]["checklist"]["expected_knowledge_categories"]
    assert body["install_result"]["knowledge_templates"]["created_categories"]


def test_validate_detects_missing_channel(client_tenant_admin):
    client_tenant_admin.post(
        "/api/v1/onboarding/select-blueprint",
        json={"blueprint_id": "dental_clinic"},
    )

    resp = client_tenant_admin.post("/api/v1/onboarding/validate")

    assert resp.status_code == 200, resp.text
    assert "channel_connected" in _blocking_codes(resp.json())


def test_validate_detects_missing_knowledge(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    _set_selected_blueprint(tenant_id)
    _seed_channel(tenant_id)
    _seed_agent(tenant_id)
    _seed_field(tenant_id)
    _seed_pipeline(tenant_id)

    resp = client_tenant_admin.post("/api/v1/onboarding/validate")

    assert resp.status_code == 200, resp.text
    assert "knowledge_ready" in _blocking_codes(resp.json())


def test_validate_distinguishes_draft_templates_from_active_knowledge(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    resp = client_tenant_admin.post(
        "/api/v1/onboarding/select-blueprint",
        json={"blueprint_id": "automotive_real_estate"},
    )
    assert resp.status_code == 200, resp.text
    _seed_channel(tenant_id)

    validation = client_tenant_admin.post("/api/v1/onboarding/validate")

    assert validation.status_code == 200, validation.text
    knowledge = next(
        check for check in validation.json()["checks"] if check["code"] == "knowledge_ready"
    )
    assert knowledge["passed"] is False
    assert knowledge["metadata"]["knowledge_state"] == "draft_template_empty"
    assert knowledge["metadata"]["draft_template_count"] > 0
    assert validation.json()["state"]["knowledge_uploaded"] is False


def test_validate_detects_missing_agent(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    _set_selected_blueprint(tenant_id)
    _seed_channel(tenant_id)
    _seed_field(tenant_id)
    _seed_pipeline(tenant_id)
    _seed_knowledge(tenant_id)

    resp = client_tenant_admin.post("/api/v1/onboarding/validate")

    assert resp.status_code == 200, resp.text
    assert "active_agent" in _blocking_codes(resp.json())


def test_publish_readiness_false_if_test_not_passed(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    _set_selected_blueprint(tenant_id)
    _seed_channel(tenant_id)
    _seed_agent(tenant_id)
    _seed_field(tenant_id)
    _seed_pipeline(tenant_id)
    _seed_knowledge(tenant_id)

    resp = client_tenant_admin.post("/api/v1/onboarding/publish-readiness")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is False
    assert body["blocking_codes"] == ["test_passed"]
    assert body["readiness"] is None


def test_publish_readiness_refleja_readiness_real(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    _set_selected_blueprint(tenant_id)
    _seed_channel(tenant_id)
    agent_id = _seed_agent(tenant_id)
    _seed_field(tenant_id)
    _seed_pipeline(tenant_id)
    _seed_knowledge(tenant_id)
    _seed_readiness(tenant_id, agent_id, passed=True)

    resp = client_tenant_admin.post("/api/v1/onboarding/publish-readiness")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is True
    assert body["state"]["test_passed"] is True
    assert body["readiness"]["passed"] is True
    assert body["readiness"]["agent_id"] == agent_id


def test_tenant_isolation(client_tenant_admin):
    other_tenant_id, other_blueprint = _seed_other_tenant_state()
    try:
        resp = client_tenant_admin.get("/api/v1/onboarding/state")
    finally:
        _delete_tenant(other_tenant_id)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_id"] == client_tenant_admin.tenant_id
    assert body["selected_blueprint_id"] != other_blueprint

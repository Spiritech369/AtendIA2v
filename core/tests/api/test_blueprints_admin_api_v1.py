from __future__ import annotations

import asyncio
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


def _db_all(sql: str, params: dict | None = None) -> list[dict]:
    async def _run() -> list[dict]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                rows = (await conn.execute(text(sql), params or {})).mappings().all()
                return [dict(row) for row in rows]
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


def _seed_other_tenant_field(field_key: str) -> str:
    async def _run() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"blueprint_admin_other_{uuid4().hex[:8]}"},
                    )
                ).scalar_one()
                await conn.execute(
                    text(
                        "INSERT INTO customer_field_definitions "
                        "(id, tenant_id, key, label, field_type, ordering) "
                        "VALUES (:id, :t, :k, 'Other tenant field', 'text', 1)"
                    ),
                    {"id": str(uuid4()), "t": tenant_id, "k": field_key},
                )
            return str(tenant_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _delete_tenant(tenant_id: str) -> None:
    _db_execute("DELETE FROM tenants WHERE id = :t", {"t": tenant_id})


def test_operator_cannot_use_blueprints_admin_api(client_operator):
    resp = client_operator.get("/api/v1/blueprints")

    assert resp.status_code == 403


def test_list_and_preview_install_are_tenant_scoped(client_tenant_admin):
    other_tenant_id = _seed_other_tenant_field("patient_need")
    try:
        listing = client_tenant_admin.get("/api/v1/blueprints")
        preview = client_tenant_admin.post("/api/v1/blueprints/dental_clinic/preview-install")
    finally:
        _delete_tenant(other_tenant_id)

    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json()} == {
        "automotive_real_estate",
        "beauty_barber_spa",
        "dental_clinic",
    }
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["agent_template"]["name"]
    assert body["enabled_actions"]
    assert set(body["knowledge_categories"]) >= {
        "services",
        "pricing",
        "appointment_rules",
        "policy",
    }
    assert body["workflow_draft_templates"]
    assert body["eval_scenarios"]
    assert "patient_need" in {field["key"] for field in body["fields_to_create"]}
    assert body["existing_fields"] == []
    assert {risk["code"] for risk in body["risks"]} >= {
        "knowledge_required",
        "workflow_drafts_inactive",
    }


def test_install_blueprint_is_idempotent_updates_onboarding_and_audits(client_tenant_admin):
    first = client_tenant_admin.post("/api/v1/blueprints/beauty_barber_spa/install")
    second = client_tenant_admin.post("/api/v1/blueprints/beauty_barber_spa/install")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["created_field_keys"]
    assert first.json()["created_lifecycle_stage_ids"]
    assert first.json()["agent_created"] is True
    assert second.json()["already_installed"] is True
    assert second.json()["created_field_keys"] == []
    assert second.json()["created_lifecycle_stage_ids"] == []
    state = client_tenant_admin.get("/api/v1/onboarding/state").json()
    assert state["selected_blueprint_id"] == "beauty_barber_spa"
    assert state["checklist"]["expected_knowledge_categories"]
    event_count = _db_scalar(
        "SELECT COUNT(*) FROM events WHERE tenant_id = :t AND type = 'admin.blueprint.installed'",
        {"t": client_tenant_admin.tenant_id},
    )
    assert event_count == 2


def test_install_does_not_create_or_activate_workflows(client_tenant_admin):
    resp = client_tenant_admin.post("/api/v1/blueprints/automotive_real_estate/install")

    assert resp.status_code == 200, resp.text
    workflow_count = _db_scalar(
        "SELECT COUNT(*) FROM workflows WHERE tenant_id = :t",
        {"t": client_tenant_admin.tenant_id},
    )
    assert workflow_count == 0


def test_create_knowledge_templates_is_draft_and_idempotent(client_tenant_admin):
    first = client_tenant_admin.post(
        "/api/v1/blueprints/automotive_real_estate/create-knowledge-templates"
    )
    second = client_tenant_admin.post(
        "/api/v1/blueprints/automotive_real_estate/create-knowledge-templates"
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["created_categories"] == [
        "catalog",
        "pricing",
        "services",
        "appointment_rules",
        "document_rules",
        "policy",
    ]
    assert second.json()["already_created"] is True
    rows = _db_all(
        "SELECT status, metadata_json FROM knowledge_sources WHERE tenant_id = :t",
        {"t": client_tenant_admin.tenant_id},
    )
    assert {row["status"] for row in rows} == {"draft"}
    assert all(row["metadata_json"]["template_empty"] is True for row in rows)
    assert client_tenant_admin.get("/api/v1/onboarding/state").json()["knowledge_uploaded"] is False


def test_create_workflow_drafts_never_publishes_and_is_idempotent(client_tenant_admin):
    first = client_tenant_admin.post(
        "/api/v1/blueprints/dental_clinic/create-workflow-drafts"
    )
    second = client_tenant_admin.post(
        "/api/v1/blueprints/dental_clinic/create-workflow-drafts"
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["created_template_ids"]
    assert second.json()["already_created"] is True
    rows = _db_all(
        "SELECT active, trigger_type, trigger_config, definition "
        "FROM workflows WHERE tenant_id = :t",
        {"t": client_tenant_admin.tenant_id},
    )
    assert rows
    assert {row["active"] for row in rows} == {False}
    assert all(row["trigger_type"] != "webhook_received" for row in rows)
    assert all(row["trigger_config"]["safe_draft"] is True for row in rows)
    assert all(row["definition"]["metadata"]["blueprint_id"] == "dental_clinic" for row in rows)
    assert all(row["definition"]["metadata"]["status"] == "draft" for row in rows)
    event_count = _db_scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE tenant_id = :t AND type = 'admin.blueprint.workflow_drafts.created'",
        {"t": client_tenant_admin.tenant_id},
    )
    assert event_count == 1


def test_blueprint_admin_api_does_not_mix_tenants(client_tenant_admin, client_superadmin):
    tenant_admin_install = client_tenant_admin.post(
        "/api/v1/blueprints/dental_clinic/install"
    )
    superadmin_preview = client_superadmin.post(
        "/api/v1/blueprints/dental_clinic/preview-install"
    )

    assert tenant_admin_install.status_code == 200, tenant_admin_install.text
    assert superadmin_preview.status_code == 200, superadmin_preview.text
    assert superadmin_preview.json()["existing_fields"] == []

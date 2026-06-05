from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.agent_runtime import ActionRequest, AgentRuntime, TurnOutput
from atendia.api import agents_routes
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


def _create_agent(client, **overrides) -> dict:
    body = {
        "name": f"Studio Agent {uuid4().hex[:8]}",
        "role": "support",
        "is_default": False,
        "active_intents": ["GREETING"],
    }
    body.update(overrides)
    resp = client.post("/api/v1/agents", json=body)
    assert resp.status_code == 201, resp.text
    _set_rollout(
        client.tenant_id,
        rollout_mode="preview",
        runtime_v2_enabled=True,
        shadow_mode_enabled=True,
        preview_enabled=True,
        send_enabled=False,
        actions_enabled=False,
        workflow_events_enabled=False,
        model_provider_enabled=False,
    )
    return resp.json()


def _set_rollout(tenant_id: str, **policy) -> None:
    _db_execute(
        "UPDATE tenants SET config = jsonb_set("
        "coalesce(config, '{}'::jsonb), '{agent_runtime_v2}', "
        "CAST(:policy AS jsonb), true) WHERE id = :t",
        {"t": tenant_id, "policy": json.dumps(policy)},
    )


@pytest.fixture(autouse=True)
def _agent_runtime_v2_enabled(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER", "disabled")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_faq(tenant_id: str, *, question: str, answer: str) -> str:
    return str(
        _db_scalar(
            "INSERT INTO tenant_faqs (tenant_id, question, answer, tags, status) "
            "VALUES (:t, :q, :a, CAST('[]' AS jsonb), 'published') RETURNING id",
            {"t": tenant_id, "q": question, "a": answer},
        )
    )


def _seed_catalog(tenant_id: str, *, sku: str, name: str) -> str:
    return str(
        _db_scalar(
            "INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs, active, status) "
            "VALUES (:t, :sku, :name, CAST('{}' AS jsonb), true, 'published') "
            "RETURNING id",
            {"t": tenant_id, "sku": sku, "name": name},
        )
    )


def _seed_native_source(tenant_id: str, *, name: str) -> str:
    source_id = str(uuid4())
    _db_execute(
        "INSERT INTO knowledge_sources "
        "(id, tenant_id, name, type, content_type, status) "
        "VALUES (:id, :t, :name, 'manual', 'policy', 'draft')",
        {"id": source_id, "t": tenant_id, "name": name},
    )
    return str(
        source_id
    )


def _seed_contact_field(tenant_id: str, key: str, label: str) -> None:
    _db_execute(
        "INSERT INTO customer_field_definitions "
        "(id, tenant_id, key, label, field_type, field_options, ordering) "
        "VALUES (:id, :t, :k, :l, 'text', NULL, 10)",
        {"id": str(uuid4()), "t": tenant_id, "k": key, "l": label},
    )


def _seed_pipeline(tenant_id: str, stage_ids: list[str]) -> None:
    definition = {
        "stages": [{"id": stage_id, "label": stage_id.title()} for stage_id in stage_ids]
    }
    _db_execute(
        "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
        "VALUES (:t, :v, CAST(:d AS jsonb), true)",
        {
            "t": tenant_id,
            "v": 900000 + uuid4().int % 9999,
            "d": json.dumps(definition),
        },
    )


def _seed_other_tenant_source() -> tuple[str, str]:
    async def _run() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"agent_studio_other_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                faq_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO tenant_faqs "
                            "(tenant_id, question, answer, tags, status) "
                            "VALUES (:t, 'Secret source', 'Other tenant only', "
                            "CAST('[]' AS jsonb), 'published') RETURNING id"
                        ),
                        {"t": tenant_id},
                    )
                ).scalar()
                return str(tenant_id), str(faq_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _delete_tenant(tenant_id: str) -> None:
    _db_execute("DELETE FROM tenants WHERE id = :t", {"t": tenant_id})


def test_agent_studio_v2_config_roundtrip(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    faq_id = _seed_faq(
        tenant_id,
        question=f"Warranty {uuid4().hex[:8]}",
        answer="Warranty policy is tenant-owned.",
    )
    _seed_contact_field(tenant_id, "email", "Email")
    _seed_pipeline(tenant_id, ["new", "qualified"])

    agent = _create_agent(
        client_tenant_admin,
        template="support",
        instructions="Answer only from approved sources.",
        language_policy={"primary": "es-MX", "mode": "match_customer"},
        enabled_knowledge_source_ids=[faq_id],
        enabled_action_ids=["add_tag"],
        visible_contact_field_keys=["email"],
        allowed_lifecycle_stage_ids=["qualified"],
        escalation_policy={"mode": "human_on_low_confidence"},
        metadata={"studio": "v2"},
    )

    assert agent["template"] == "support"
    assert agent["instructions"] == "Answer only from approved sources."
    assert agent["enabled_knowledge_source_ids"] == [faq_id]
    assert agent["enabled_action_ids"] == ["add_tag"]
    assert agent["visible_contact_field_keys"] == ["email"]
    assert agent["allowed_lifecycle_stage_ids"] == ["qualified"]
    assert agent["knowledge_config"]["enabled_source_ids"] == [faq_id]
    assert agent["auto_actions"]["enabled_action_ids"] == ["add_tag"]

    config = client_tenant_admin.get(f"/api/v1/agents/{agent['id']}/config")
    assert config.status_code == 200, config.text
    assert config.json()["instructions"] == "Answer only from approved sources."
    assert config.json()["enabled_action_ids"] == ["add_tag"]


def test_agent_studio_v2_safe_defaults_for_legacy_agent(client_tenant_admin):
    agent = _create_agent(client_tenant_admin)

    detail = client_tenant_admin.get(f"/api/v1/agents/{agent['id']}")

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["instructions"] == ""
    assert body["enabled_action_ids"] == []
    assert body["enabled_knowledge_source_ids"] == []
    assert body["language_policy"]["primary"] == "es"


def test_agent_studio_v2_rejects_unknown_action(client_tenant_admin):
    agent = _create_agent(client_tenant_admin)

    resp = client_tenant_admin.patch(
        f"/api/v1/agents/{agent['id']}",
        json={"enabled_action_ids": ["invent_pdf"]},
    )

    assert resp.status_code == 422
    assert "unknown enabled_action_ids" in resp.text


def test_agent_studio_v2_rejects_knowledge_source_from_other_tenant(client_tenant_admin):
    other_tenant_id, other_faq_id = _seed_other_tenant_source()
    try:
        agent = _create_agent(client_tenant_admin)
        resp = client_tenant_admin.patch(
            f"/api/v1/agents/{agent['id']}",
            json={"enabled_knowledge_source_ids": [other_faq_id]},
        )
    finally:
        _delete_tenant(other_tenant_id)

    assert resp.status_code == 422
    assert "outside tenant" in resp.text


def test_agent_studio_v2_lists_available_resources(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    native_id = _seed_native_source(tenant_id, name=f"Native {uuid4().hex[:8]}")
    faq_id = _seed_faq(
        tenant_id,
        question=f"Coverage {uuid4().hex[:8]}",
        answer="Coverage source.",
    )
    catalog_id = _seed_catalog(
        tenant_id,
        sku=f"ST-{uuid4().hex[:6]}",
        name=f"Studio catalog {uuid4().hex[:6]}",
    )
    _seed_contact_field(tenant_id, "phone_confirmed", "Phone confirmed")
    _seed_pipeline(tenant_id, ["intake", "done"])

    actions = client_tenant_admin.get("/api/v1/agents/studio/actions")
    knowledge = client_tenant_admin.get("/api/v1/agents/studio/knowledge-sources")
    fields = client_tenant_admin.get("/api/v1/agents/studio/contact-fields")
    stages = client_tenant_admin.get("/api/v1/agents/studio/lifecycle-stages")

    assert actions.status_code == 200
    assert any(item["id"] == "add_tag" for item in actions.json())
    assert knowledge.status_code == 200
    assert knowledge.json()[0]["id"] == native_id
    assert knowledge.json()[0]["metadata"]["badge"] == "native"
    assert any(item["id"] == faq_id for item in knowledge.json())
    catalog = next(item for item in knowledge.json() if item["id"] == catalog_id)
    assert catalog["metadata"]["badge"] == "legacy"
    assert catalog["metadata"]["legacy_table"] == "tenant_catalogs"
    assert fields.status_code == 200
    assert any(item["id"] == "phone_confirmed" for item in fields.json())
    assert stages.status_code == 200
    assert any(item["id"] == "done" for item in stages.json())


def test_agent_runtime_rejects_action_not_enabled_for_agent(monkeypatch, client_tenant_admin):
    agent = _create_agent(client_tenant_admin, enabled_action_ids=["add_tag"])

    class _ActionProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="Listo.",
                confidence=0.9,
                actions=[
                    ActionRequest(
                        name="update_contact_field",
                        payload={"field_key": "email", "value": "a@b.test"},
                        reason="Test action.",
                    )
                ],
            )

    def _runtime(context):
        return AgentRuntime(
            context_builder=agents_routes._StaticContextBuilder(context),
            provider=_ActionProvider(),
        )

    monkeypatch.setattr(agents_routes, "_build_test_turn_runtime", _runtime)
    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent['id']}/test-turn-v2",
        json={"test_message": "Update email"},
    )

    assert resp.status_code == 422
    assert "unknown_action" in resp.text


def test_agent_runtime_filters_knowledge_sources_by_agent_config(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    allowed_id = _seed_faq(
        tenant_id,
        question=f"Quartz allowed {uuid4().hex[:8]}",
        answer="Allowed tenant quartz source.",
    )
    _seed_faq(
        tenant_id,
        question=f"Quartz blocked {uuid4().hex[:8]}",
        answer="Blocked tenant quartz source.",
    )
    agent = _create_agent(client_tenant_admin, enabled_knowledge_source_ids=[allowed_id])

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent['id']}/test-turn-v2",
        json={"test_message": "quartz source"},
    )

    assert resp.status_code == 200, resp.text
    citations = resp.json()["knowledge_citations"]
    assert citations
    assert {item["source_id"] for item in citations} == {allowed_id}


def test_agent_runtime_filters_visible_contact_fields(client_tenant_admin):
    _seed_contact_field(client_tenant_admin.tenant_id, "email", "Email")
    agent = _create_agent(client_tenant_admin, visible_contact_field_keys=["email"])

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent['id']}/test-turn-v2",
        json={
            "test_message": "Hello",
            "contact_fields": [
                {"key": "email", "label": "Email", "field_type": "text"},
                {"key": "internal_score", "label": "Internal score", "field_type": "number"},
            ],
        },
    )

    assert resp.status_code == 200, resp.text
    assert "contact_fields=1" in resp.json()["debug"]["context_summary"]

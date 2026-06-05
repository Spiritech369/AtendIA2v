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


def _create_agent(client, *, name: str = "Test Agent", **overrides) -> str:
    body = {
        "name": name,
        "role": "support",
        "is_default": False,
        "active_intents": ["GREETING"],
    }
    body.update(overrides)
    resp = client.post(
        "/api/v1/agents",
        json=body,
    )
    assert resp.status_code == 201, resp.text
    agent_id = resp.json()["id"]
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
    return agent_id


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


def _seed_catalog(tenant_id: str, *, sku: str, name: str, attrs: dict | None = None) -> str:
    return str(
        _db_scalar(
            "INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs, active, status) "
            "VALUES (:t, :sku, :name, CAST(:attrs AS jsonb), true, 'published') "
            "RETURNING id",
            {
                "t": tenant_id,
                "sku": sku,
                "name": name,
                "attrs": json.dumps(attrs or {}),
            },
        )
    )


def _seed_document_chunk(tenant_id: str, *, filename: str, chunk_text: str) -> str:
    document_id = str(
        _db_scalar(
            "INSERT INTO knowledge_documents "
            "(tenant_id, filename, storage_path, category, status, fragment_count) "
            "VALUES (:t, :filename, :path, 'policy', 'indexed', 1) RETURNING id",
            {
                "t": tenant_id,
                "filename": filename,
                "path": f"{tenant_id}/{filename}",
            },
        )
    )
    _db_scalar(
        "INSERT INTO knowledge_chunks "
        "(document_id, tenant_id, chunk_index, text, chunk_status) "
        "VALUES (:d, :t, 0, :text, 'embedded') RETURNING id",
        {"d": document_id, "t": tenant_id, "text": chunk_text},
    )
    return document_id


def _seed_native_source(tenant_id: str, *, name: str, content: str) -> str:
    source_id = str(uuid4())
    _db_execute(
        "INSERT INTO knowledge_sources "
        "(id, tenant_id, name, type, content_type, status) "
        "VALUES (:id, :t, :name, 'manual', 'policy', 'active')",
        {"id": source_id, "t": tenant_id, "name": name},
    )
    item_id = str(uuid4())
    _db_execute(
        "INSERT INTO knowledge_items "
        "(id, tenant_id, source_id, title, content, status, active) "
        "VALUES (:id, :t, :source, :name, :content, 'active', true)",
        {
            "id": item_id,
            "t": tenant_id,
            "source": source_id,
            "name": name,
            "content": content,
        },
    )
    _db_execute(
        "INSERT INTO knowledge_os_chunks "
        "(id, tenant_id, source_id, item_id, chunk_text, chunk_index, status) "
        "VALUES (:id, :t, :source, :item, :content, 0, 'active')",
        {
            "id": str(uuid4()),
            "t": tenant_id,
            "source": source_id,
            "item": item_id,
            "content": content,
        },
    )
    return source_id


def _seed_other_tenant_agent_and_faq() -> tuple[str, str]:
    async def _run() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"agent_test_turn_other_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                agent_id = (
                    await conn.execute(
                        text("INSERT INTO agents (tenant_id, name) VALUES (:t, :n) RETURNING id"),
                        {"t": tenant_id, "n": "Other Tenant Agent"},
                    )
                ).scalar()
                await conn.execute(
                    text(
                        "INSERT INTO tenant_faqs (tenant_id, question, answer, tags, status) "
                        "VALUES (:t, :q, :a, CAST('[]' AS jsonb), 'published')"
                    ),
                    {
                        "t": tenant_id,
                        "q": "Delivery window",
                        "a": "Other tenant delivery happens on Friday.",
                    },
                )
            return str(tenant_id), str(agent_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _seed_other_tenant_catalog() -> tuple[str, str]:
    async def _run() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"agent_test_catalog_other_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                catalog_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO tenant_catalogs "
                            "(tenant_id, sku, name, attrs, active, status) "
                            "VALUES (:t, 'OTHER-QTZ', 'Quartz Other Catalog', "
                            "CAST('{\"engine\":\"999cc\"}' AS jsonb), true, 'published') "
                            "RETURNING id"
                        ),
                        {"t": tenant_id},
                    )
                ).scalar()
                return str(tenant_id), str(catalog_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _delete_tenant(tenant_id: str) -> None:
    _db_execute("DELETE FROM tenants WHERE id = :t", {"t": tenant_id})


def _message_count(tenant_id: str) -> int:
    return int(
        _db_scalar("SELECT COUNT(*) FROM messages WHERE tenant_id = :t", {"t": tenant_id}) or 0
    )


def _readiness_count(tenant_id: str, agent_id: str) -> int:
    return int(
        _db_scalar(
            "SELECT COUNT(*) FROM agent_readiness_eval_results "
            "WHERE tenant_id = :t AND agent_id = :a",
            {"t": tenant_id, "a": agent_id},
        )
        or 0
    )


def test_test_turn_v2_returns_citations_and_does_not_create_messages(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    _seed_faq(
        client_tenant_admin.tenant_id,
        question="Support hours",
        answer="Support hours are Monday morning.",
    )
    before = _message_count(client_tenant_admin.tenant_id)

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "What are support hours Monday?"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["final_message"]
    assert body["knowledge_citations"]
    assert body["debug"]["retrieval"]["answerable"] is True
    assert body["debug"]["side_effects"]["persisted_messages"] is False
    assert _message_count(client_tenant_admin.tenant_id) == before


def test_test_turn_v2_guarda_readiness_evidence_exitosa(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    _seed_faq(
        client_tenant_admin.tenant_id,
        question="Support hours",
        answer="Support hours are Monday morning.",
    )
    before = _readiness_count(client_tenant_admin.tenant_id, agent_id)

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={
            "test_message": "What are support hours Monday?",
            "save_readiness_evidence": True,
            "requires_knowledge_citation": True,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debug"]["readiness"]["passed"] is True
    assert _readiness_count(client_tenant_admin.tenant_id, agent_id) == before + 1


def test_test_turn_v2_no_pasa_readiness_si_requiere_knowledge_sin_citations(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={
            "test_message": "Hello there",
            "save_readiness_evidence": True,
            "requires_knowledge_citation": True,
        },
    )

    assert resp.status_code == 200, resp.text
    readiness = resp.json()["debug"]["readiness"]
    assert readiness["passed"] is False
    assert readiness["policy_failures"][0]["scorer"] == "required_knowledge_citations"


def test_test_turn_v2_works_without_knowledge(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "Hello there"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["knowledge_citations"] == []
    assert body["debug"]["retrieval"]["answerable"] is False


def test_test_turn_v2_respects_tenant_isolation(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    _seed_faq(
        client_tenant_admin.tenant_id,
        question="Delivery window",
        answer="Own tenant delivery happens on Monday.",
    )
    other_tenant_id, _other_agent_id = _seed_other_tenant_agent_and_faq()
    try:
        resp = client_tenant_admin.post(
            f"/api/v1/agents/{agent_id}/test-turn-v2",
            json={"test_message": "Delivery window Monday"},
        )
    finally:
        _delete_tenant(other_tenant_id)

    assert resp.status_code == 200, resp.text
    snippets = " ".join(citation["snippet"] for citation in resp.json()["knowledge_citations"])
    assert "Own tenant" in snippets
    assert "Other tenant" not in snippets


def test_test_turn_v2_returns_legacy_catalog_citations(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    catalog_id = _seed_catalog(
        client_tenant_admin.tenant_id,
        sku=f"CAT-{uuid4().hex[:6]}",
        name="Quartz Scooter",
        attrs={"engine": "125cc", "color": "blue"},
    )

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "Quartz Scooter 125cc"},
    )

    assert resp.status_code == 200, resp.text
    citations = resp.json()["knowledge_citations"]
    assert any(item["source_id"] == catalog_id for item in citations)
    assert any(item["metadata"]["legacy_table"] == "tenant_catalogs" for item in citations)


def test_test_turn_v2_legacy_catalog_is_tenant_scoped(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    catalog_id = _seed_catalog(
        client_tenant_admin.tenant_id,
        sku=f"OWN-{uuid4().hex[:6]}",
        name="Quartz Own Catalog",
        attrs={"engine": "125cc"},
    )
    other_tenant_id, other_catalog_id = _seed_other_tenant_catalog()
    try:
        resp = client_tenant_admin.post(
            f"/api/v1/agents/{agent_id}/test-turn-v2",
            json={"test_message": "Quartz Catalog"},
        )
    finally:
        _delete_tenant(other_tenant_id)

    assert resp.status_code == 200, resp.text
    citation_ids = {item["source_id"] for item in resp.json()["knowledge_citations"]}
    assert catalog_id in citation_ids
    assert other_catalog_id not in citation_ids


def test_test_turn_v2_returns_legacy_document_chunk_citations(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    document_id = _seed_document_chunk(
        client_tenant_admin.tenant_id,
        filename=f"policy-{uuid4().hex[:6]}.txt",
        chunk_text="The warranty transfer policy requires original receipt validation.",
    )

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "warranty transfer receipt validation"},
    )

    assert resp.status_code == 200, resp.text
    citations = resp.json()["knowledge_citations"]
    assert any(item["source_id"] == document_id for item in citations)
    assert any(item["metadata"]["legacy_table"] == "knowledge_chunks" for item in citations)


def test_test_turn_v2_can_mix_native_and_legacy_adapted_sources(client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)
    native_id = _seed_native_source(
        client_tenant_admin.tenant_id,
        name="Native Sapphire Policy",
        content="Sapphire policy is the native Knowledge OS source.",
    )
    faq_id = _seed_faq(
        client_tenant_admin.tenant_id,
        question="Sapphire FAQ",
        answer="Sapphire FAQ is the adapted legacy source.",
    )

    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "Sapphire source policy FAQ"},
    )

    assert resp.status_code == 200, resp.text
    citation_ids = {item["source_id"] for item in resp.json()["knowledge_citations"]}
    assert {native_id, faq_id}.issubset(citation_ids)


def test_test_turn_v2_blocks_agent_from_other_tenant(client_tenant_admin):
    other_tenant_id, other_agent_id = _seed_other_tenant_agent_and_faq()
    try:
        resp = client_tenant_admin.post(
            f"/api/v1/agents/{other_agent_id}/test-turn-v2",
            json={"test_message": "Hello"},
        )
    finally:
        _delete_tenant(other_tenant_id)

    assert resp.status_code == 404


def test_operator_cannot_use_test_turn_v2(client_operator, client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)

    resp = client_operator.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "Hello"},
    )

    assert resp.status_code in (403, 404)


def test_test_turn_v2_does_not_execute_actions_real(monkeypatch, client_tenant_admin):
    agent_id = _create_agent(
        client_tenant_admin,
        enabled_action_ids=["update_contact_field"],
    )

    class _ActionProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="Listo.",
                confidence=0.9,
                actions=[
                        ActionRequest(
                            name="update_contact_field",
                            payload={"field_key": "priority", "value": "high"},
                            reason="Test harness only.",
                            evidence=["Please mark priority"],
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
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "Please mark priority"},
    )

    assert resp.status_code == 200, resp.text
    result = resp.json()["debug"]["actions"]["results"][0]
    assert result["status"] == "skipped"
    assert result["trace_metadata"]["dry_run"] is True


def test_test_turn_v2_rejects_invalid_runtime_output(monkeypatch, client_tenant_admin):
    agent_id = _create_agent(client_tenant_admin)

    class _InvalidProvider:
        async def generate(self, context):
            return TurnOutput(final_message="", confidence=0.9, needs_human=False)

    def _runtime(context):
        return AgentRuntime(
            context_builder=agents_routes._StaticContextBuilder(context),
            provider=_InvalidProvider(),
        )

    monkeypatch.setattr(agents_routes, "_build_test_turn_runtime", _runtime)
    resp = client_tenant_admin.post(
        f"/api/v1/agents/{agent_id}/test-turn-v2",
        json={"test_message": "Hello"},
    )

    assert resp.status_code == 422
    assert "missing_final_message" in str(resp.json())

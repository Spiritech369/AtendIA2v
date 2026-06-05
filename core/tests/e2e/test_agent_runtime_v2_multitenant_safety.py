from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.agent_runtime import ActionRequest, AgentRuntime, TurnOutput
from atendia.agent_runtime.post_turn_executor import PostTurnActionExecutor
from atendia.agent_runtime.schemas import CustomerContext, TurnContext
from atendia.agent_runtime.shadow_service import SHADOW_ROUTER_TRIGGER, AgentRuntimeShadowService
from atendia.api import conversations_routes
from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.contact_memory.service import ContactMemoryService
from atendia.lifecycle.service import LifecycleService
from atendia.main import app


@dataclass(frozen=True)
class TenantEnv:
    tenant_id: str
    user_id: str
    client: TestClient
    agent_id: str
    source_id: str
    customer_id: str
    conversation_id: str
    message_id: str
    workflow_id: str
    field_key: str
    unique_marker: str


@dataclass(frozen=True)
class E2EEnv:
    a: TenantEnv
    b: TenantEnv


def _run(coro):
    return asyncio.run(coro)


def _db_scalar(sql: str, params: dict | None = None):
    async def _inner():
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                return (await conn.execute(text(sql), params or {})).scalar()
        finally:
            await engine.dispose()

    return _run(_inner())


def _db_execute(sql: str, params: dict | None = None) -> None:
    async def _inner():
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params or {})
        finally:
            await engine.dispose()

    _run(_inner())


def _json(value: dict | list) -> str:
    return json.dumps(value, ensure_ascii=False)


def _create_client_for_tenant(tenant_id: str, user_id: str, email: str, password: str) -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    client.headers["X-CSRF-Token"] = resp.json()["csrf_token"]
    client.tenant_id = tenant_id  # type: ignore[attr-defined]
    client.user_id = user_id  # type: ignore[attr-defined]
    return client


def _policy(*, agent_id: str, send: bool, actions: bool = False, workflows: bool = False) -> dict:
    return {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": True,
        "preview_enabled": True,
        "send_enabled": send,
        "actions_enabled": actions,
        "workflow_events_enabled": workflows,
        "model_provider_enabled": False,
        "allowed_agent_ids": [agent_id],
        "allowed_channel_ids": ["whatsapp"],
        "required_eval_suite_passed": False,
        "rollout_mode": "manual_send" if send else "preview",
    }


def _seed_tenant(label: str, *, send: bool) -> TenantEnv:
    password = "test-password-123"
    email = f"agent_v2_e2e_{label}_{uuid4().hex[:8]}@example.com"
    unique_marker = f"{label.upper()}_ONLY_{uuid4().hex[:8]}"
    field_key = f"budget_{label}_{uuid4().hex[:5]}"
    hashed = hash_password(password)

    async def _inner() -> tuple[str, str, str, str, str, str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name, config) VALUES (:n, '{}') RETURNING id"),
                        {"n": f"agent_v2_e2e_{label}_{uuid4().hex[:8]}"},
                    )
                ).scalar_one()
                user_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO tenant_users "
                            "(tenant_id, email, role, password_hash) "
                            "VALUES (:t, :e, 'tenant_admin', :h) RETURNING id"
                        ),
                        {"t": tenant_id, "e": email, "h": hashed},
                    )
                ).scalar_one()
                source_id = uuid4()
                item_id = uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO knowledge_sources "
                        "(id, tenant_id, name, type, content_type, status) "
                        "VALUES (:id, :t, :n, 'manual', 'pricing', 'active')"
                    ),
                    {"id": source_id, "t": tenant_id, "n": f"Source {label}"},
                )
                await conn.execute(
                    text(
                        "INSERT INTO knowledge_items "
                        "(id, tenant_id, source_id, title, content, status, active) "
                        "VALUES (:id, :t, :s, :title, :content, 'active', true)"
                    ),
                    {
                        "id": item_id,
                        "t": tenant_id,
                        "s": source_id,
                        "title": f"Pricing {label}",
                        "content": f"{unique_marker} price is 123.",
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO knowledge_os_chunks "
                        "(id, tenant_id, source_id, item_id, chunk_text, chunk_index, status) "
                        "VALUES (:id, :t, :s, :i, :txt, 0, 'active')"
                    ),
                    {
                        "id": uuid4(),
                        "t": tenant_id,
                        "s": source_id,
                        "i": item_id,
                        "txt": f"{unique_marker} price is 123.",
                    },
                )
                agent_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO agents "
                            "(tenant_id, name, role, status, knowledge_config, auto_actions) "
                            "VALUES (:t, :n, 'support', 'production', "
                            "CAST(:knowledge AS jsonb), CAST(:actions AS jsonb)) "
                            "RETURNING id"
                        ),
                        {
                            "t": tenant_id,
                            "n": f"Agent {label}",
                            "knowledge": _json({"enabled_source_ids": [str(source_id)]}),
                            "actions": _json({"enabled_action_ids": ["add_tag", "update_contact_field"]}),
                        },
                    )
                ).scalar_one()
                await conn.execute(
                    text(
                        "UPDATE tenants SET config = CAST(:config AS jsonb) WHERE id = :t"
                    ),
                    {
                        "t": tenant_id,
                        "config": _json({"agent_runtime_v2": _policy(agent_id=str(agent_id), send=send)}),
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO customer_field_definitions "
                        "(id, tenant_id, key, label, field_type, field_options, ordering) "
                        "VALUES (:id, :t, :k, :label, 'text', CAST(:options AS jsonb), 1)"
                    ),
                    {
                        "id": uuid4(),
                        "t": tenant_id,
                        "k": field_key,
                        "label": f"Budget {label}",
                        "options": _json(
                            {
                                "contact_memory": {
                                    "write_policy": "ai_auto",
                                    "confidence_threshold": 0.8,
                                    "evidence_required": True,
                                }
                            }
                        ),
                    },
                )
                pipeline = {
                    "version": 1,
                    "stages": [
                        {"id": "new", "label": "New"},
                        {"id": "qualified", "label": "Qualified"},
                    ],
                }
                await conn.execute(
                    text(
                        "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
                        "VALUES (:t, :v, CAST(:d AS jsonb), true)"
                    ),
                    {"t": tenant_id, "v": 970000 + uuid4().int % 10000, "d": _json(pipeline)},
                )
                customer_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, :n) RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+52155{uuid4().hex[:8]}", "n": f"Customer {label}"},
                    )
                ).scalar_one()
                conversation_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, assigned_agent_id, current_stage, channel) "
                            "VALUES (:t, :c, :a, 'new', 'whatsapp') RETURNING id"
                        ),
                        {"t": tenant_id, "c": customer_id, "a": agent_id},
                    )
                ).scalar_one()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conversation_id},
                )
                message_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO messages "
                            "(conversation_id, tenant_id, direction, text, sent_at) "
                            "VALUES (:c, :t, 'inbound', :txt, now()) RETURNING id"
                        ),
                        {"c": conversation_id, "t": tenant_id, "txt": f"precio {unique_marker}"},
                    )
                ).scalar_one()
                workflow_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflows "
                            "(tenant_id, name, trigger_type, trigger_config, definition, active) "
                            "VALUES (:t, :n, 'agent_confidence_low', "
                            "CAST(:trigger_config AS jsonb), "
                            "CAST(:definition AS jsonb), true) "
                            "RETURNING id"
                        ),
                        {
                            "t": tenant_id,
                            "n": f"WF {label}",
                            "trigger_config": _json({"confidence_lte": 0.5}),
                            "definition": _json({"nodes": [], "edges": []}),
                        },
                    )
                ).scalar_one()
                return (
                    str(tenant_id),
                    str(user_id),
                    str(agent_id),
                    str(source_id),
                    str(customer_id),
                    str(conversation_id),
                    str(message_id),
                    str(workflow_id),
                )
        finally:
            await engine.dispose()

    (
        tenant_id,
        user_id,
        agent_id,
        source_id,
        customer_id,
        conversation_id,
        message_id,
        workflow_id,
    ) = _run(_inner())
    return TenantEnv(
        tenant_id=tenant_id,
        user_id=user_id,
        client=_create_client_for_tenant(tenant_id, user_id, email, password),
        agent_id=agent_id,
        source_id=source_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        message_id=message_id,
        workflow_id=workflow_id,
        field_key=field_key,
        unique_marker=unique_marker,
    )


def _delete_tenant(tenant_id: str) -> None:
    _db_execute("DELETE FROM tenants WHERE id = :t", {"t": tenant_id})


def _set_policy(env: TenantEnv, **overrides) -> None:
    policy = _policy(
        agent_id=env.agent_id,
        send=overrides.pop("send", True),
        actions=overrides.pop("actions", False),
        workflows=overrides.pop("workflows", False),
    )
    policy.update(overrides)
    _db_execute(
        "UPDATE tenants SET config = CAST(:config AS jsonb) WHERE id = :t",
        {"t": env.tenant_id, "config": _json({"agent_runtime_v2": policy})},
    )


@pytest.fixture
def e2e_env(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER", "disabled")
    get_settings.cache_clear()
    env = E2EEnv(a=_seed_tenant("a", send=True), b=_seed_tenant("b", send=False))
    try:
        yield env
    finally:
        _delete_tenant(env.a.tenant_id)
        _delete_tenant(env.b.tenant_id)
        get_settings.cache_clear()


def _outbox_count(tenant_id: str) -> int:
    return int(_db_scalar("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :t", {"t": tenant_id}) or 0)


def _workflow_execution_count(workflow_id: str) -> int:
    return int(
        _db_scalar(
            "SELECT COUNT(*) FROM workflow_executions WHERE workflow_id = :w",
            {"w": workflow_id},
        )
        or 0
    )


def _action_log_count(tenant_id: str, *, dry_run: bool | None = None) -> int:
    clause = "" if dry_run is None else " AND dry_run = :dry"
    return int(
        _db_scalar(
            "SELECT COUNT(*) FROM action_execution_logs WHERE tenant_id = :t" + clause,
            {"t": tenant_id, "dry": dry_run},
        )
        or 0
    )


def _conversation_tags(conversation_id: str) -> list[str]:
    return list(
        _db_scalar(
            "SELECT tags FROM conversations WHERE id = :c",
            {"c": conversation_id},
        )
        or []
    )


def _field_value(customer_id: str, field_key: str) -> str | None:
    return _db_scalar(
        "SELECT cfv.value FROM customer_field_values cfv "
        "JOIN customer_field_definitions cfd ON cfd.id = cfv.field_definition_id "
        "WHERE cfv.customer_id = :c AND cfd.key = :k",
        {"c": customer_id, "k": field_key},
    )


def _stage(conversation_id: str) -> str | None:
    return _db_scalar("SELECT current_stage FROM conversations WHERE id = :c", {"c": conversation_id})


def _trace_count(tenant_id: str, trigger: str | None = None) -> int:
    clause = "" if trigger is None else " AND router_trigger = :trigger"
    return int(
        _db_scalar(
            "SELECT COUNT(*) FROM turn_traces WHERE tenant_id = :t" + clause,
            {"t": tenant_id, "trigger": trigger},
        )
        or 0
    )


def _runtime_with_provider(provider):
    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=provider,
        )

    return _runtime


class _ActionProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo, lo dejo anotado.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="add_tag",
                    payload={"tag": "safety-test"},
                    reason="Safety dry-run proposal.",
                    evidence=[context.inbound_text],
                )
            ],
        )


class _UnknownActionProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="call_webhook",
                    payload={"webhook_id": "blocked"},
                    reason="Should be disabled for this agent.",
                    evidence=[context.inbound_text],
                    requires_approval=True,
                )
            ],
        )


class _LowConfidenceProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="No tengo ese dato confirmado; lo escalo para revisarlo.",
            confidence=0.4,
            needs_human=True,
            risk_flags=["knowledge_gap"],
        )


def test_migration_tables_exist():
    assert _db_scalar("SELECT to_regclass('agent_readiness_eval_results')") is not None
    assert _db_scalar("SELECT to_regclass('action_execution_logs')") is not None
    assert _db_scalar("SELECT to_regclass('lifecycle_stage_history')") is not None


def test_preview_por_tenant_usa_solo_su_knowledge(e2e_env):
    resp_a = e2e_env.a.client.post(
        f"/api/v1/conversations/{e2e_env.a.conversation_id}/agent-runtime-v2/preview"
    )
    resp_b = e2e_env.b.client.post(
        f"/api/v1/conversations/{e2e_env.b.conversation_id}/agent-runtime-v2/preview"
    )

    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    snippets_a = " ".join(item["snippet"] for item in resp_a.json()["knowledge_citations"])
    snippets_b = " ".join(item["snippet"] for item in resp_b.json()["knowledge_citations"])
    assert e2e_env.a.unique_marker in snippets_a
    assert e2e_env.b.unique_marker not in snippets_a
    assert e2e_env.b.unique_marker in snippets_b
    assert e2e_env.a.unique_marker not in snippets_b
    assert _trace_count(e2e_env.a.tenant_id) == 1
    assert _trace_count(e2e_env.b.tenant_id) == 1


def test_agent_no_puede_usar_acciones_no_habilitadas(monkeypatch, e2e_env):
    _db_execute(
        "UPDATE agents SET auto_actions = CAST(:actions AS jsonb) WHERE id = :a",
        {"a": e2e_env.a.agent_id, "actions": _json({"enabled_action_ids": ["update_contact_field"]})},
    )
    monkeypatch.setattr(
        conversations_routes,
        "_build_conversation_agent_runtime",
        _runtime_with_provider(_UnknownActionProvider()),
    )

    resp = e2e_env.a.client.post(
        f"/api/v1/conversations/{e2e_env.a.conversation_id}/agent-runtime-v2/preview"
    )

    assert resp.status_code == 422
    assert "unknown_action" in resp.text or "sensitive_action" in resp.text


def test_contact_memory_y_lifecycle_no_cruzan_tenants(e2e_env):
    async def _inner():
        engine = create_async_engine(get_settings().database_url)
        try:
            async_session = async_sessionmaker(engine, expire_on_commit=False)
            async with async_session() as session:
                context = TurnContext(
                    tenant_id=e2e_env.a.tenant_id,
                    conversation_id=e2e_env.a.conversation_id,
                    inbound_text="mi presupuesto es 9000",
                    customer=CustomerContext(id=e2e_env.a.customer_id),
                )
                output = TurnOutput(
                    final_message="Listo.",
                    confidence=0.95,
                    actions=[
                        ActionRequest(
                            name="update_contact_field",
                            payload={"field_key": e2e_env.a.field_key, "value": "9000"},
                            reason="Customer gave budget.",
                            evidence=["mi presupuesto es 9000"],
                        ),
                        ActionRequest(
                            name="move_lifecycle",
                            payload={"target_stage": "qualified"},
                            reason="Customer shared qualifying information.",
                            evidence=["mi presupuesto es 9000"],
                        ),
                    ],
                )
                results = await PostTurnActionExecutor(
                    dry_run=False,
                    session=session,
                    contact_memory_service=ContactMemoryService(session),
                    lifecycle_service=LifecycleService(session),
                    require_runtime_enabled=False,
                ).execute(output, context=context)
                await session.commit()
                return [result.model_dump(mode="json") for result in results]
        finally:
            await engine.dispose()

    results = _run(_inner())

    assert any(result["action_name"] == "update_contact_field" for result in results)
    assert _field_value(e2e_env.a.customer_id, e2e_env.a.field_key) == "9000"
    assert _field_value(e2e_env.b.customer_id, e2e_env.b.field_key) is None
    assert _stage(e2e_env.a.conversation_id) == "qualified"
    assert _stage(e2e_env.b.conversation_id) == "new"
    assert _action_log_count(e2e_env.a.tenant_id, dry_run=False) >= 2
    assert _action_log_count(e2e_env.b.tenant_id) == 0
    assert int(
        _db_scalar(
            "SELECT COUNT(*) FROM lifecycle_stage_history WHERE tenant_id = :t",
            {"t": e2e_env.a.tenant_id},
        )
        or 0
    ) == 1
    assert int(
        _db_scalar(
            "SELECT COUNT(*) FROM lifecycle_stage_history WHERE tenant_id = :t",
            {"t": e2e_env.b.tenant_id},
        )
        or 0
    ) == 0


def test_send_bloqueado_por_policy_y_send_stagea_solo_tenant_a(monkeypatch, e2e_env):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    before_a = _outbox_count(e2e_env.a.tenant_id)
    before_b = _outbox_count(e2e_env.b.tenant_id)

    blocked = e2e_env.b.client.post(
        f"/api/v1/conversations/{e2e_env.b.conversation_id}/agent-runtime-v2/send"
    )
    sent = e2e_env.a.client.post(
        f"/api/v1/conversations/{e2e_env.a.conversation_id}/agent-runtime-v2/send"
    )

    assert blocked.status_code == 403
    assert "tenant send is false" in blocked.text
    assert sent.status_code == 200, sent.text
    assert _outbox_count(e2e_env.a.tenant_id) == before_a + 1
    assert _outbox_count(e2e_env.b.tenant_id) == before_b


def test_actions_dry_run_no_modifican_datos(monkeypatch, e2e_env):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "true")
    get_settings.cache_clear()
    _set_policy(e2e_env.a, send=True, actions=False)
    monkeypatch.setattr(
        conversations_routes,
        "_build_conversation_agent_runtime",
        _runtime_with_provider(_ActionProvider()),
    )

    resp = e2e_env.a.client.post(
        f"/api/v1/conversations/{e2e_env.a.conversation_id}/agent-runtime-v2/send"
    )

    assert resp.status_code == 200, resp.text
    assert _conversation_tags(e2e_env.a.conversation_id) == []
    assert _action_log_count(e2e_env.a.tenant_id, dry_run=True) >= 1
    assert _action_log_count(e2e_env.b.tenant_id) == 0


def test_workflow_events_dry_run_no_crea_executions(monkeypatch, e2e_env):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    _set_policy(e2e_env.a, send=True, workflows=False)
    monkeypatch.setattr(
        conversations_routes,
        "_build_conversation_agent_runtime",
        _runtime_with_provider(_LowConfidenceProvider()),
    )

    resp = e2e_env.a.client.post(
        f"/api/v1/conversations/{e2e_env.a.conversation_id}/agent-runtime-v2/send"
    )

    assert resp.status_code == 200, resp.text
    assert all(event["simulated"] is True for event in resp.json()["debug"]["workflow_events"])
    assert _workflow_execution_count(e2e_env.a.workflow_id) == 0
    assert _workflow_execution_count(e2e_env.b.workflow_id) == 0


def test_workflow_events_reales_solo_con_global_y_tenant_policy(monkeypatch, e2e_env):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    _set_policy(e2e_env.a, send=True, workflows=True)
    _set_policy(e2e_env.b, send=True, workflows=False)
    monkeypatch.setattr(
        conversations_routes,
        "_build_conversation_agent_runtime",
        _runtime_with_provider(_LowConfidenceProvider()),
    )

    resp_a = e2e_env.a.client.post(
        f"/api/v1/conversations/{e2e_env.a.conversation_id}/agent-runtime-v2/send"
    )
    resp_b = e2e_env.b.client.post(
        f"/api/v1/conversations/{e2e_env.b.conversation_id}/agent-runtime-v2/send"
    )

    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    assert any(event["simulated"] is False for event in resp_a.json()["debug"]["workflow_events"])
    assert all(event["simulated"] is True for event in resp_b.json()["debug"]["workflow_events"])
    assert _workflow_execution_count(e2e_env.a.workflow_id) == 1
    assert _workflow_execution_count(e2e_env.b.workflow_id) == 0


def test_shadow_no_side_effects_e_idempotencia(e2e_env):
    async def _inner():
        engine = create_async_engine(get_settings().database_url)
        try:
            async_session = async_sessionmaker(engine, expire_on_commit=False)
            async with async_session() as session:
                service = AgentRuntimeShadowService(session)
                first = await service.run_shadow_for_inbound(
                    tenant_id=UUID(e2e_env.a.tenant_id),
                    conversation_id=UUID(e2e_env.a.conversation_id),
                    inbound_message_id=UUID(e2e_env.a.message_id),
                    inbound_text=f"precio {e2e_env.a.unique_marker}",
                    legacy_output=["legacy answer"],
                )
                second = await service.run_shadow_for_inbound(
                    tenant_id=UUID(e2e_env.a.tenant_id),
                    conversation_id=UUID(e2e_env.a.conversation_id),
                    inbound_message_id=UUID(e2e_env.a.message_id),
                    inbound_text=f"precio {e2e_env.a.unique_marker}",
                    legacy_output=["legacy answer"],
                )
                await session.commit()
                return first.status, second.status
        finally:
            await engine.dispose()

    before_outbox = _outbox_count(e2e_env.a.tenant_id)
    first_status, second_status = _run(_inner())

    assert first_status == "shadowed"
    assert second_status == "skipped"
    assert _outbox_count(e2e_env.a.tenant_id) == before_outbox
    assert _trace_count(e2e_env.a.tenant_id, SHADOW_ROUTER_TRIGGER) == 1
    assert _trace_count(e2e_env.b.tenant_id, SHADOW_ROUTER_TRIGGER) == 0

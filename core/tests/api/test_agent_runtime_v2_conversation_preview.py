from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.agent_runtime import ActionRequest, AgentRuntime, TurnOutput
from atendia.api import conversations_routes
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


def _seed_conversation(
    tenant_id: str,
    *,
    inbound_text: str = "Hola, cuanto cuesta?",
    inbound_age_hours: float = 1.0,
    bot_paused: bool = False,
    assigned_agent_id: str | None = None,
) -> str:
    async def _run() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                customer_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Eval Cliente') RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conversation_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, assigned_agent_id) "
                            "VALUES (:t, :c, :a) RETURNING id"
                        ),
                        {"t": tenant_id, "c": customer_id, "a": assigned_agent_id},
                    )
                ).scalar()
                await conn.execute(
                    text(
                        "INSERT INTO conversation_state (conversation_id, bot_paused) "
                        "VALUES (:c, :paused)"
                    ),
                    {"c": conversation_id, "paused": bot_paused},
                )
                sent_at = datetime.now(UTC) - timedelta(hours=inbound_age_hours)
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'inbound', :txt, :s)"
                    ),
                    {
                        "c": conversation_id,
                        "t": tenant_id,
                        "txt": inbound_text,
                        "s": sent_at,
                    },
                )
                return str(conversation_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _seed_agent(tenant_id: str) -> str:
    return str(
        _db_scalar(
            "INSERT INTO agents (tenant_id, name, status) "
            "VALUES (:t, :n, 'production') RETURNING id",
            {"t": tenant_id, "n": f"runtime_v2_agent_{uuid4().hex[:8]}"},
        )
    )


def _enable_agent_actions(agent_id: str, actions: list[str]) -> None:
    _db_execute(
        "UPDATE agents SET auto_actions = jsonb_set("
        "coalesce(auto_actions, '{}'::jsonb), '{enabled_action_ids}', "
        "CAST(:actions AS jsonb), true) WHERE id = :a",
        {"a": agent_id, "actions": json.dumps(actions)},
    )


def _seed_readiness(tenant_id: str, agent_id: str, *, score: float = 1.0) -> None:
    _db_execute(
        "INSERT INTO agent_readiness_eval_results "
        "(id, tenant_id, agent_id, suite_id, score, passed, scenario_count, "
        "failed_scenarios, policy_failures, metadata) "
        "VALUES (:id, :t, :a, 'agent_runtime_v2_minimum_readiness', "
        ":score, true, 1, CAST('[]' AS jsonb), CAST('[]' AS jsonb), "
        "CAST('{}' AS jsonb))",
        {"id": str(uuid4()), "t": tenant_id, "a": agent_id, "score": score},
    )


def _seed_shadow_trace(
    tenant_id: str,
    conversation_id: str,
    agent_id: str,
    *,
    confidence: float = 0.95,
) -> None:
    _db_execute(
        "INSERT INTO turn_traces "
        "(tenant_id, conversation_id, turn_number, router_trigger, agent_id, composer_output) "
        "VALUES (:t, :c, "
        "COALESCE((SELECT MAX(turn_number) + 1 FROM turn_traces WHERE conversation_id = :c), 1), "
        "'agent_runtime_v2_shadow', :a, CAST(:output AS jsonb))",
        {
            "t": tenant_id,
            "c": conversation_id,
            "a": agent_id,
            "output": json.dumps({"confidence": confidence, "final_message": "Shadow ok."}),
        },
    )


def _seed_other_tenant_conversation() -> tuple[str, str]:
    async def _run() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tenant_id = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"agent_runtime_v2_other_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                customer_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164) "
                            "VALUES (:t, :p) RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conversation_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id) "
                            "VALUES (:t, :c) RETURNING id"
                        ),
                        {"t": tenant_id, "c": customer_id},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conversation_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'inbound', 'hola', now())"
                    ),
                    {"c": conversation_id, "t": tenant_id},
                )
            return str(tenant_id), str(conversation_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _counts(tenant_id: str, conversation_id: str) -> dict[str, int]:
    return {
        "messages": int(
            _db_scalar(
                "SELECT COUNT(*) FROM messages WHERE tenant_id = :t AND conversation_id = :c",
                {"t": tenant_id, "c": conversation_id},
            )
            or 0
        ),
        "outbox": int(
            _db_scalar(
                "SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :t",
                {"t": tenant_id},
            )
            or 0
        ),
        "traces": int(
            _db_scalar(
                "SELECT COUNT(*) FROM turn_traces WHERE tenant_id = :t AND conversation_id = :c",
                {"t": tenant_id, "c": conversation_id},
            )
            or 0
        ),
        "agent_events": int(
            _db_scalar(
                "SELECT COUNT(*) FROM events WHERE tenant_id = :t "
                "AND conversation_id = :c AND type LIKE 'agent_%'",
                {"t": tenant_id, "c": conversation_id},
            )
            or 0
        ),
    }


def _seed_workflow(
    tenant_id: str,
    *,
    trigger_type: str,
    trigger_config: str = "{}",
) -> str:
    return str(
        _db_scalar(
            "INSERT INTO workflows "
            "(tenant_id, name, trigger_type, trigger_config, definition, active) "
            "VALUES (:t, :n, :tt, CAST(:tc AS jsonb), "
            "CAST('{\"nodes\":[],\"edges\":[]}' AS jsonb), true) "
            "RETURNING id",
            {
                "t": tenant_id,
                "n": f"agent_runtime_v2_wf_{uuid4().hex[:8]}",
                "tt": trigger_type,
                "tc": trigger_config,
            },
        )
    )


def _workflow_execution_count(workflow_id: str) -> int:
    return int(
        _db_scalar(
            "SELECT COUNT(*) FROM workflow_executions WHERE workflow_id = :w",
            {"w": workflow_id},
        )
        or 0
    )


def _latest_trace_state_after(tenant_id: str, conversation_id: str) -> dict:
    return (
        _db_scalar(
            "SELECT state_after FROM turn_traces "
            "WHERE tenant_id = :t AND conversation_id = :c "
            "ORDER BY created_at DESC, turn_number DESC LIMIT 1",
            {"t": tenant_id, "c": conversation_id},
        )
        or {}
    )


def _outbox_payload(outbox_id: str) -> dict:
    return (
        _db_scalar(
            "SELECT payload FROM outbound_outbox WHERE id = :id",
            {"id": outbox_id},
        )
        or {}
    )


def _set_rollout(tenant_id: str, **overrides) -> dict:
    policy = {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": True,
        "preview_enabled": True,
        "send_enabled": True,
        "actions_enabled": True,
        "workflow_events_enabled": True,
        "model_provider_enabled": False,
        "rollout_mode": "manual_send",
        "metadata": {"eval_suite_passed": True, "eval_score": 1.0},
    }
    policy.update(overrides)
    _db_execute(
        "UPDATE tenants SET config = jsonb_set("
        "coalesce(config, '{}'::jsonb), '{agent_runtime_v2}', "
        "CAST(:policy AS jsonb), true) WHERE id = :t",
        {"t": tenant_id, "policy": json.dumps(policy)},
    )
    return policy


def _pilot_config(
    tenant_id: str,
    agent_id: str,
    **overrides,
) -> dict:
    policy = {
        "enabled": True,
        "allowed_tenant_ids": [tenant_id],
        "allowed_agent_ids": [agent_id],
        "max_sends_per_day": 5,
        "require_latest_readiness_passed": True,
        "min_readiness_score": 0.9,
        "min_shadow_sample_size": 0,
        "min_shadow_score": None,
        "actions_dry_run_required": True,
        "workflow_events_dry_run_required": True,
    }
    policy.update(overrides)
    return policy


@pytest.fixture
def _agent_runtime_flags(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_preview_no_envia_y_crea_trace(client_tenant_admin, _agent_runtime_flags):
    _set_rollout(
        client_tenant_admin.tenant_id,
        rollout_mode="preview",
        send_enabled=False,
        actions_enabled=False,
        workflow_events_enabled=False,
    )
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/preview"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["final_message"]
    assert body["debug"]["side_effects"]["persisted_messages"] is False
    assert body["debug"]["workflow_events"]
    assert all(event["simulated"] is True for event in body["debug"]["workflow_events"])
    after = _counts(client_tenant_admin.tenant_id, conversation_id)
    assert after["messages"] == before["messages"]
    assert after["outbox"] == before["outbox"]
    assert after["traces"] == before["traces"] + 1
    assert after["agent_events"] == before["agent_events"]


def test_send_bloqueado_si_flag_apagado(client_tenant_admin, _agent_runtime_flags):
    _set_rollout(client_tenant_admin.tenant_id, send_enabled=True)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    assert resp.status_code == 403
    assert "global flag blocks send" in resp.text


def test_send_bloqueado_si_readiness_no_existe(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=True,
        min_eval_score=0.9,
    )
    conversation_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 403
    assert "readiness result is missing" in resp.text


def test_send_permitido_si_readiness_paso(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _enable_agent_actions(agent_id, ["add_tag"])
    _seed_readiness(client_tenant_admin.tenant_id, agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=True,
        min_eval_score=0.9,
    )
    conversation_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debug"]["rollout"]["send"]["allowed"] is True
    assert body["debug"]["rollout"]["send"]["policy"]["readiness"]["ready"] is True


def test_send_usa_outbox_cuando_flag_activo(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id, actions_enabled=False)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_id"] == body["outbox_id"]
    assert body["debug"]["side_effects"]["persisted_messages"] is True
    assert body["debug"]["side_effects"]["staged_outbox"] is True
    after = _counts(client_tenant_admin.tenant_id, conversation_id)
    assert after["messages"] == before["messages"] + 1
    assert after["outbox"] == before["outbox"] + 1
    assert after["traces"] == before["traces"] + 1


def test_pilot_send_permitido_solo_si_tenant_y_agent_allowlisted(
    monkeypatch,
    client_tenant_admin,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    get_settings.cache_clear()
    allowed_agent_id = _seed_agent(client_tenant_admin.tenant_id)
    blocked_agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _seed_readiness(client_tenant_admin.tenant_id, allowed_agent_id, score=0.95)
    _seed_readiness(client_tenant_admin.tenant_id, blocked_agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=False,
        pilot=_pilot_config(client_tenant_admin.tenant_id, allowed_agent_id),
    )
    allowed_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=allowed_agent_id,
    )
    blocked_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=blocked_agent_id,
    )

    ok = client_tenant_admin.post(
        f"/api/v1/conversations/{allowed_conversation}/agent-runtime-v2/send"
    )
    blocked = client_tenant_admin.post(
        f"/api/v1/conversations/{blocked_conversation}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert ok.status_code == 200, ok.text
    assert ok.json()["debug"]["pilot"]["allowed"] is True
    assert blocked.status_code == 403
    assert "agent_id is not allowlisted for pilot" in blocked.text


def test_pilot_send_bloqueado_sin_readiness(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=False,
        pilot=_pilot_config(client_tenant_admin.tenant_id, agent_id),
    )
    conversation_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 403
    assert "readiness result is missing" in resp.text
    state_after = _latest_trace_state_after(client_tenant_admin.tenant_id, conversation_id)
    assert state_after["pilot"]["allowed"] is False


def test_pilot_send_bloqueado_si_excede_max_per_day(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _seed_readiness(client_tenant_admin.tenant_id, agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=False,
        pilot=_pilot_config(
            client_tenant_admin.tenant_id,
            agent_id,
            max_sends_per_day=1,
        ),
    )
    first_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )
    second_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )

    first = client_tenant_admin.post(
        f"/api/v1/conversations/{first_conversation}/agent-runtime-v2/send"
    )
    second = client_tenant_admin.post(
        f"/api/v1/conversations/{second_conversation}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert first.status_code == 200, first.text
    assert second.status_code == 403
    assert "max_sends_per_day" in second.text


def test_pilot_exige_shadow_sample_y_score_minimos(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _seed_readiness(client_tenant_admin.tenant_id, agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=False,
        pilot=_pilot_config(
            client_tenant_admin.tenant_id,
            agent_id,
            min_shadow_sample_size=1,
            min_shadow_score=0.9,
        ),
    )
    blocked_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )
    allowed_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )

    blocked = client_tenant_admin.post(
        f"/api/v1/conversations/{blocked_conversation}/agent-runtime-v2/send"
    )
    _seed_shadow_trace(
        client_tenant_admin.tenant_id,
        allowed_conversation,
        agent_id,
        confidence=0.95,
    )
    allowed = client_tenant_admin.post(
        f"/api/v1/conversations/{allowed_conversation}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert blocked.status_code == 403
    assert "shadow sample size" in blocked.text
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["debug"]["pilot"]["shadow_sample_size"] >= 1


def test_pilot_fuerza_actions_y_workflows_dry_run_y_registra_trace(
    monkeypatch,
    client_tenant_admin,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _enable_agent_actions(agent_id, ["add_tag"])
    _seed_readiness(client_tenant_admin.tenant_id, agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        actions_enabled=True,
        workflow_events_enabled=True,
        required_eval_suite_passed=False,
        pilot=_pilot_config(client_tenant_admin.tenant_id, agent_id),
    )
    conversation_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )
    workflow_id = _seed_workflow(
        client_tenant_admin.tenant_id,
        trigger_type="agent_confidence_low",
        trigger_config='{"confidence_lte":0.5}',
    )

    class _PilotProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="Lo reviso con el equipo y te confirmo.",
                confidence=0.4,
                needs_human=True,
                risk_flags=["knowledge_gap"],
                actions=[
                    ActionRequest(
                        name="add_tag",
                        payload={"tag": "pilot"},
                        reason="Pilot dry-run.",
                        evidence=[context.inbound_text],
                    )
                ],
            )

    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=_PilotProvider(),
        )

    monkeypatch.setattr(conversations_routes, "_build_conversation_agent_runtime", _runtime)
    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debug"]["side_effects"]["sent_whatsapp_direct"] is False
    assert body["debug"]["actions"]["results"][0]["trace_metadata"]["dry_run"] is True
    assert all(event["simulated"] is True for event in body["debug"]["workflow_events"])
    assert _workflow_execution_count(workflow_id) == 0
    payload = _outbox_payload(body["outbox_id"])
    assert payload["metadata"]["pilot"]["allowed"] is True
    state_after = _latest_trace_state_after(client_tenant_admin.tenant_id, conversation_id)
    assert state_after["pilot"]["allowed"] is True
    assert state_after["actions_dry_run"] is True


def test_pilot_rollback_policy_deshabilita_send(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _seed_readiness(client_tenant_admin.tenant_id, agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=False,
        pilot=_pilot_config(
            client_tenant_admin.tenant_id,
            agent_id,
            enabled=False,
            rollback_disabled=True,
        ),
    )
    conversation_id = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )
    before = _counts(client_tenant_admin.tenant_id, conversation_id)

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 403
    assert "rollback is active" in resp.text
    assert _counts(client_tenant_admin.tenant_id, conversation_id)["outbox"] == before["outbox"]


def test_pilot_report_resume_sends_y_failures(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    _seed_readiness(client_tenant_admin.tenant_id, agent_id, score=0.95)
    _set_rollout(
        client_tenant_admin.tenant_id,
        required_eval_suite_passed=False,
        pilot=_pilot_config(
            client_tenant_admin.tenant_id,
            agent_id,
            max_sends_per_day=1,
        ),
    )
    first_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )
    second_conversation = _seed_conversation(
        client_tenant_admin.tenant_id,
        assigned_agent_id=agent_id,
    )
    client_tenant_admin.post(
        f"/api/v1/conversations/{first_conversation}/agent-runtime-v2/send"
    )
    client_tenant_admin.post(
        f"/api/v1/conversations/{second_conversation}/agent-runtime-v2/send"
    )

    resp = client_tenant_admin.get("/api/v1/agent-runtime-v2/pilot-report")

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["sends"] >= 1
    assert report["policy_failures"] >= 1
    assert report["average_confidence"] is not None
    assert report["error_rate"] >= 0


def test_no_ejecuta_acciones_reales_si_flag_apagado(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id, actions_enabled=True)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)

    class _ActionProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="Listo.",
                confidence=0.9,
                actions=[
                    ActionRequest(
                        name="add_tag",
                        payload={"tag": "test"},
                        reason="Manual v2 test.",
                        evidence=[context.inbound_text],
                    )
                ],
            )

    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=_ActionProvider(),
        )

    monkeypatch.setattr(conversations_routes, "_build_conversation_agent_runtime", _runtime)
    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    action_result = resp.json()["debug"]["actions"]["results"][0]
    assert action_result["status"] == "skipped"
    assert action_result["trace_metadata"]["dry_run"] is True


def test_acciones_reales_bloqueadas_si_tenant_actions_false(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "true")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id, actions_enabled=False)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)

    class _ActionProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="Listo.",
                confidence=0.9,
                actions=[
                    ActionRequest(
                        name="add_tag",
                        payload={"tag": "tenant-blocked"},
                        reason="Manual v2 test.",
                        evidence=[context.inbound_text],
                    )
                ],
            )

    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=_ActionProvider(),
        )

    monkeypatch.setattr(conversations_routes, "_build_conversation_agent_runtime", _runtime)
    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    action_result = body["debug"]["actions"]["results"][0]
    assert action_result["trace_metadata"]["dry_run"] is True
    assert body["debug"]["rollout"]["actions"]["allowed"] is False


def test_tenant_isolation_en_preview(client_tenant_admin, _agent_runtime_flags):
    other_tenant_id, conversation_id = _seed_other_tenant_conversation()
    try:
        resp = client_tenant_admin.post(
            f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/preview"
        )
    finally:
        _db_execute("DELETE FROM tenants WHERE id = :t", {"t": other_tenant_id})

    assert resp.status_code == 404


def test_shadow_no_produce_side_effects(client_tenant_admin, _agent_runtime_flags):
    _set_rollout(
        client_tenant_admin.tenant_id,
        rollout_mode="shadow",
        preview_enabled=False,
        send_enabled=False,
        actions_enabled=False,
        workflow_events_enabled=False,
    )
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/shadow"
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["debug"]["mode"] == "shadow"
    assert body["debug"]["side_effects"]["persisted_messages"] is False
    assert body["debug"]["side_effects"]["staged_outbox"] is False
    assert all(event["simulated"] is True for event in body["debug"]["workflow_events"])
    after = _counts(client_tenant_admin.tenant_id, conversation_id)
    assert after["messages"] == before["messages"]
    assert after["outbox"] == before["outbox"]
    assert after["agent_events"] == before["agent_events"]
    assert after["traces"] == before["traces"] + 1


def test_humano_pausado_bloquea_send(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id, bot_paused=True)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)

    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 409
    assert "paused by human" in resp.text
    assert _counts(client_tenant_admin.tenant_id, conversation_id)["outbox"] == before["outbox"]


def test_output_invalido_no_se_envia(monkeypatch, client_tenant_admin):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)

    class _InvalidProvider:
        async def generate(self, context):
            return TurnOutput(final_message="", confidence=0.9, needs_human=False)

    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=_InvalidProvider(),
        )

    monkeypatch.setattr(conversations_routes, "_build_conversation_agent_runtime", _runtime)
    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 422
    after = _counts(client_tenant_admin.tenant_id, conversation_id)
    assert after["messages"] == before["messages"]
    assert after["outbox"] == before["outbox"]
    assert after["traces"] == before["traces"] + 1


def test_send_emite_evento_real_y_dispara_workflow_si_flag_activo(
    monkeypatch,
    client_tenant_admin,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id, workflow_events_enabled=True)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)
    workflow_id = _seed_workflow(
        client_tenant_admin.tenant_id,
        trigger_type="agent_confidence_low",
        trigger_config='{"confidence_lte":0.5}',
    )

    class _LowConfidenceProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="No tengo ese dato confirmado; lo escalo para revisarlo.",
                confidence=0.4,
                needs_human=True,
                risk_flags=["knowledge_gap"],
            )

    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=_LowConfidenceProvider(),
        )

    monkeypatch.setattr(conversations_routes, "_build_conversation_agent_runtime", _runtime)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)
    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    workflow_events = resp.json()["debug"]["workflow_events"]
    assert any(event["type"] == "agent_confidence_low" for event in workflow_events)
    assert all(event["simulated"] is False for event in workflow_events)
    assert _workflow_execution_count(workflow_id) == 1
    after = _counts(client_tenant_admin.tenant_id, conversation_id)
    assert after["agent_events"] >= before["agent_events"] + 1


def test_workflow_events_reales_bloqueados_si_tenant_false(
    monkeypatch,
    client_tenant_admin,
):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "true")
    get_settings.cache_clear()
    _set_rollout(client_tenant_admin.tenant_id, workflow_events_enabled=False)
    conversation_id = _seed_conversation(client_tenant_admin.tenant_id)
    workflow_id = _seed_workflow(
        client_tenant_admin.tenant_id,
        trigger_type="agent_confidence_low",
        trigger_config='{"confidence_lte":0.5}',
    )

    class _LowConfidenceProvider:
        async def generate(self, context):
            return TurnOutput(
                final_message="No tengo ese dato confirmado; lo escalo para revisarlo.",
                confidence=0.4,
                needs_human=True,
                risk_flags=["knowledge_gap"],
            )

    def _runtime(context):
        return AgentRuntime(
            context_builder=conversations_routes._StaticContextBuilder(context),
            provider=_LowConfidenceProvider(),
        )

    monkeypatch.setattr(conversations_routes, "_build_conversation_agent_runtime", _runtime)
    before = _counts(client_tenant_admin.tenant_id, conversation_id)
    resp = client_tenant_admin.post(
        f"/api/v1/conversations/{conversation_id}/agent-runtime-v2/send"
    )

    get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    workflow_events = body["debug"]["workflow_events"]
    assert any(event["type"] == "agent_confidence_low" for event in workflow_events)
    assert all(event["simulated"] is True for event in workflow_events)
    assert body["debug"]["rollout"]["workflow_events"]["allowed"] is False
    assert _workflow_execution_count(workflow_id) == 0
    after = _counts(client_tenant_admin.tenant_id, conversation_id)
    assert after["agent_events"] == before["agent_events"]

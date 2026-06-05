from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
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


def _seed_agent(tenant_id: str) -> str:
    return str(
        _db_scalar(
            "INSERT INTO agents (tenant_id, name, status) "
            "VALUES (:t, :n, 'production') RETURNING id",
            {"t": tenant_id, "n": f"shadow_analytics_agent_{uuid4().hex[:8]}"},
        )
    )


def _seed_conversation(
    tenant_id: str,
    *,
    agent_id: str | None = None,
    channel: str = "whatsapp_meta",
) -> str:
    async def _run() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                customer_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Shadow Cliente') RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conversation_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, assigned_agent_id, channel) "
                            "VALUES (:t, :c, :a, :channel) RETURNING id"
                        ),
                        {
                            "t": tenant_id,
                            "c": customer_id,
                            "a": agent_id,
                            "channel": channel,
                        },
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conversation_id},
                )
                return str(conversation_id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _seed_other_tenant() -> tuple[str, str, str]:
    tenant_id = str(
        _db_scalar(
            "INSERT INTO tenants (name) VALUES (:n) RETURNING id",
            {"n": f"shadow_analytics_other_{uuid4().hex[:8]}"},
        )
    )
    agent_id = _seed_agent(tenant_id)
    conversation_id = _seed_conversation(tenant_id, agent_id=agent_id)
    return tenant_id, agent_id, conversation_id


def _seed_shadow_trace(
    tenant_id: str,
    conversation_id: str,
    agent_id: str,
    *,
    legacy_message: str | None = "Legacy answer",
    v2_message: str | None = "V2 answer",
    confidence: float | None = 0.9,
    needs_human: bool = False,
    risk_flags: list[str] | None = None,
    actions: list[dict] | None = None,
    field_updates: list[dict] | None = None,
    lifecycle_update: dict | None = None,
    citations: list[dict] | None = None,
    policy_issues: list[dict] | None = None,
    errors: list[dict] | None = None,
    created_at: datetime | None = None,
    trigger: str = "agent_runtime_v2_shadow_auto",
) -> str:
    output = {
        "final_message": v2_message,
        "confidence": confidence,
        "needs_human": needs_human,
        "risk_flags": risk_flags or [],
        "actions": actions or [],
        "field_updates": field_updates or [],
        "lifecycle_update": lifecycle_update,
        "knowledge_citations": citations or [],
    }
    comparison = {
        "legacy_final_message": legacy_message,
        "v2_final_message": v2_message,
        "v2_confidence": confidence,
        "policy_valid": not bool(policy_issues),
        "policy_issues": policy_issues or [],
        "error_count": len(errors or []),
    }
    return str(
        _db_scalar(
            "INSERT INTO turn_traces "
            "(tenant_id, conversation_id, turn_number, router_trigger, agent_id, "
            "state_after, composer_output, kb_evidence, rules_evaluated, errors, created_at) "
            "VALUES (:t, :c, "
            "COALESCE((SELECT MAX(turn_number) + 1 FROM turn_traces "
            "WHERE conversation_id = :c), 1), "
            ":trigger, :a, CAST(:state_after AS jsonb), CAST(:output AS jsonb), "
            "CAST(:kb AS jsonb), CAST(:rules AS jsonb), CAST(:errors AS jsonb), :created_at) "
            "RETURNING id",
            {
                "t": tenant_id,
                "c": conversation_id,
                "a": agent_id,
                "trigger": trigger,
                "state_after": json.dumps(
                    {
                        "agent_runtime_v2": True,
                        "mode": "shadow_auto",
                        "comparison": comparison,
                    }
                ),
                "output": json.dumps(output),
                "kb": json.dumps({"citations": citations or []}),
                "rules": json.dumps(
                    [{"rule": "policy_valid", "passed": not bool(policy_issues)}]
                ),
                "errors": json.dumps(errors) if errors is not None else None,
                "created_at": created_at or datetime.now(UTC),
            },
        )
    )


def _cleanup_tenant(tenant_id: str) -> None:
    _db_execute("DELETE FROM tenants WHERE id = :t", {"t": tenant_id})


def _outbox_count(tenant_id: str) -> int:
    return int(
        _db_scalar("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :t", {"t": tenant_id})
        or 0
    )


def test_shadow_report_is_tenant_scoped_and_aggregates(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    agent_id = _seed_agent(tenant_id)
    conversation_id = _seed_conversation(tenant_id, agent_id=agent_id)
    other_tenant_id, other_agent_id, other_conversation_id = _seed_other_tenant()
    try:
        _seed_shadow_trace(
            tenant_id,
            conversation_id,
            agent_id,
            legacy_message="Hola, el precio es 100.",
            v2_message="Hola, el precio es 100.",
            confidence=0.9,
            citations=[{"source_id": "pricing", "source_name": "Pricing Sheet"}],
            actions=[{"action_name": "quote_preview"}],
            field_updates=[{"field_id": "budget", "value": "100"}],
            lifecycle_update={"stage": "qualified"},
        )
        _seed_shadow_trace(
            other_tenant_id,
            other_conversation_id,
            other_agent_id,
            legacy_message="No debe verse",
            v2_message="No debe verse",
            confidence=0.99,
        )

        response = client_tenant_admin.get("/api/v1/agent-runtime-v2/shadow-report")

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["summary"]["shadow_turns"] == 1
        assert payload["summary"]["avg_confidence"] == 0.9
        assert payload["summary"]["actions_proposed_count"] == 1
        assert payload["summary"]["field_updates_proposed_count"] == 1
        assert payload["summary"]["lifecycle_updates_proposed_count"] == 1
        assert payload["legacy_vs_v2"]["same_or_similar_count"] == 1
        assert payload["top_knowledge_sources"] == [{"value": "Pricing Sheet", "count": 1}]
    finally:
        _cleanup_tenant(other_tenant_id)


def test_shadow_report_handles_missing_legacy_and_detects_empty_v2(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    agent_id = _seed_agent(tenant_id)
    conversation_id = _seed_conversation(tenant_id, agent_id=agent_id)
    _seed_shadow_trace(
        tenant_id,
        conversation_id,
        agent_id,
        legacy_message=None,
        v2_message="",
        confidence=0.42,
        needs_human=True,
    )

    response = client_tenant_admin.get(
        "/api/v1/agent-runtime-v2/shadow-report",
        params={"include_examples": "true", "limit": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["legacy_vs_v2"]["legacy_empty_count"] == 1
    assert payload["legacy_vs_v2"]["v2_empty_count"] == 1
    assert payload["summary"]["needs_human_count"] == 1
    assert payload["examples"][0]["confidence"] == 0.42
    heuristic_names = {
        item["name"] for item in payload["examples"][0]["heuristics"] if item["matched"]
    }
    assert {"v2_empty", "legacy_empty", "v2_needs_human", "v2_low_confidence"} <= heuristic_names


def test_shadow_report_counts_policy_blocks_knowledge_gaps_and_limits_examples(
    client_tenant_admin,
):
    tenant_id = client_tenant_admin.tenant_id
    agent_id = _seed_agent(tenant_id)
    conversation_id = _seed_conversation(tenant_id, agent_id=agent_id)
    _seed_shadow_trace(
        tenant_id,
        conversation_id,
        agent_id,
        v2_message="No tengo ese dato.",
        confidence=0.7,
        risk_flags=["knowledge_gap"],
        policy_issues=[{"code": "blocked_topic", "message": "Blocked"}],
        errors=[{"code": "blocked_topic", "where": "policy"}],
    )
    _seed_shadow_trace(
        tenant_id,
        conversation_id,
        agent_id,
        v2_message="Otra respuesta shadow.",
        confidence=0.8,
        risk_flags=["handoff_risk"],
    )

    response = client_tenant_admin.get(
        "/api/v1/agent-runtime-v2/shadow-report",
        params={"include_examples": "true", "limit": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["shadow_turns"] == 2
    assert payload["summary"]["policy_blocked_count"] == 1
    assert payload["summary"]["knowledge_gap_count"] == 1
    assert payload["summary"]["errors_count"] == 1
    assert len(payload["examples"]) == 1
    assert {"value": "knowledge_gap", "count": 1} in payload["top_risk_flags"]
    assert {"value": "blocked_topic", "count": 1} in payload["top_policy_issues"]
    assert payload["pilot_inputs"]["shadow_sample_size"] == 2


def test_shadow_report_filters_and_has_no_side_effects(client_tenant_admin):
    tenant_id = client_tenant_admin.tenant_id
    agent_id = _seed_agent(tenant_id)
    conversation_id = _seed_conversation(
        tenant_id,
        agent_id=agent_id,
        channel="instagram",
    )
    old_conversation_id = _seed_conversation(tenant_id, agent_id=agent_id)
    before_outbox = _outbox_count(tenant_id)
    _seed_shadow_trace(
        tenant_id,
        conversation_id,
        agent_id,
        confidence=0.95,
        created_at=datetime.now(UTC),
    )
    _seed_shadow_trace(
        tenant_id,
        old_conversation_id,
        agent_id,
        confidence=0.3,
        created_at=datetime.now(UTC) - timedelta(days=3),
    )

    response = client_tenant_admin.get(
        "/api/v1/agent-runtime-v2/shadow-report",
        params={
            "conversation_id": conversation_id,
            "channel": "instagram",
            "min_confidence": "0.9",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["summary"]["shadow_turns"] == 1
    assert _outbox_count(tenant_id) == before_outbox


def test_shadow_report_requires_tenant_admin_or_superadmin(
    client_operator,
    client_superadmin,
):
    operator_response = client_operator.get("/api/v1/agent-runtime-v2/shadow-report")
    superadmin_response = client_superadmin.get("/api/v1/agent-runtime-v2/shadow-report")

    assert operator_response.status_code == 403
    assert superadmin_response.status_code == 200

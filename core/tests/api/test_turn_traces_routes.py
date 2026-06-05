"""Phase 4 T34-T35 — turn-trace list + detail."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.main import app


def _seed_with_traces() -> tuple[str, str, str, str, list[str]]:
    """Returns (tid, conv_id, email, password, [trace_ids])."""
    email = f"phase4_t34_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t34_{uuid4().hex[:8]}"},
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, 'operator', :h)"
                ),
                {"t": tid, "e": email, "h": hashed},
            )
            cust = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tid, "p": f"+5215555{uuid4().hex[:8]}"[:24]},
                )
            ).scalar()
            conv = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id) "
                        "VALUES (:t, :c) RETURNING id"
                    ),
                    {"t": tid, "c": cust},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv},
            )
            tids: list[str] = []
            for i in range(3):
                trace_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO turn_traces "
                            "(tenant_id, conversation_id, turn_number, "
                            " flow_mode, nlu_model, composer_model, "
                            " inbound_text, nlu_output, total_cost_usd, "
                            " total_latency_ms, bot_paused) "
                            "VALUES (:t, :c, :n, 'PLAN', 'gpt-4o-mini', 'gpt-4o', "
                            "        :it, :no\\:\\:jsonb, 0.0123, 250, false) "
                            "RETURNING id"
                        ),
                        {
                            "t": tid,
                            "c": conv,
                            "n": i + 1,
                            "it": f"hola turn {i}",
                            "no": json.dumps({"intent": f"intent_{i}"}),
                        },
                    )
                ).scalar()
                tids.append(str(trace_id))
        await engine.dispose()
        return str(tid), str(conv), tids

    tid, conv, tids = asyncio.run(_do())
    return tid, conv, email, plain, tids


def _seed_why_answer_trace() -> tuple[str, str, str, str, str]:
    email = f"why_answer_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)
    trace_id = str(uuid4())
    agent_id = str(uuid4())
    event_id = str(uuid4())
    workflow_id = str(uuid4())

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"why_answer_{uuid4().hex[:8]}"},
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, 'operator', :h)"
                ),
                {"t": tid, "e": email, "h": hashed},
            )
            await conn.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, status) "
                    "VALUES (:id, :t, 'Why Agent', 'production')"
                ),
                {"id": agent_id, "t": tid},
            )
            customer_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tid, "p": f"+52156{uuid4().hex[:8]}"[:24]},
                )
            ).scalar()
            conv = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, assigned_agent_id) "
                        "VALUES (:t, :c, :a) RETURNING id"
                    ),
                    {"t": tid, "c": customer_id, "a": agent_id},
                )
            ).scalar()
            field_def = (
                await conn.execute(
                    text(
                        "INSERT INTO customer_field_definitions "
                        "(id, tenant_id, key, label, field_type, ordering) "
                        "VALUES (:id, :t, 'budget', 'Budget', 'text', 1) RETURNING id"
                    ),
                    {"id": str(uuid4()), "t": tid},
                )
            ).scalar()
            composer_output = {
                "final_message": "Claro, el plan recomendado usa la política aprobada.",
                "confidence": 0.88,
                "knowledge_citations": [
                    {
                        "source_id": "source-policy",
                        "title": "Policy Source",
                        "snippet": "Approved policy snippet",
                        "score": 0.91,
                        "metadata": {"source_name": "Policy Source"},
                    }
                ],
                "field_updates": [
                    {
                        "field_key": "budget",
                        "new_value": "$10,000",
                        "reason": "Customer stated budget",
                        "confidence": 0.9,
                        "evidence": ["Tengo 10 mil"],
                    }
                ],
                "lifecycle_update": {
                    "target_stage": "qualified",
                    "reason": "Budget captured",
                    "evidence": ["Tengo 10 mil"],
                    "confidence": 0.87,
                },
                "actions": [
                    {
                        "name": "update_contact_field",
                        "payload": {"field_key": "budget"},
                    }
                ],
                "needs_human": False,
                "risk_flags": [],
            }
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(id, tenant_id, conversation_id, agent_id, turn_number, inbound_text, "
                    " composer_output, kb_evidence, state_after, rules_evaluated, "
                    " total_cost_usd, bot_paused) "
                    "VALUES (:id, :t, :c, :a, 1, 'Tengo 10 mil', "
                    " CAST(:co AS jsonb), CAST(:kb AS jsonb), CAST(:sa AS jsonb), "
                    " CAST(:rules AS jsonb), 0, false)"
                ),
                {
                    "id": trace_id,
                    "t": tid,
                    "c": conv,
                    "a": agent_id,
                    "co": json.dumps(composer_output),
                    "kb": json.dumps({"citations": composer_output["knowledge_citations"]}),
                    "sa": json.dumps(
                        {
                            "rollout": {"preview": {"allowed": True}},
                            "side_effects": {"sent_message": False},
                        }
                    ),
                    "rules": json.dumps([{"rule": "policy_valid", "passed": True}]),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO action_execution_logs "
                    "(id, tenant_id, conversation_id, action_id, input, status, result, "
                    " dry_run, trace_id) "
                    "VALUES (:id, :t, :c, :action, CAST(:input AS jsonb), :status, "
                    " CAST(:result AS jsonb), :dry, :trace)"
                ),
                {
                    "id": str(uuid4()),
                    "t": tid,
                    "c": conv,
                    "action": "update_contact_field",
                    "input": json.dumps({"field_key": "budget"}),
                    "status": "skipped",
                    "result": json.dumps({"dry_run": True}),
                    "dry": True,
                    "trace": trace_id,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO action_execution_logs "
                    "(id, tenant_id, conversation_id, action_id, input, status, result, "
                    " dry_run, trace_id) "
                    "VALUES (:id, :t, :c, :action, CAST(:input AS jsonb), :status, "
                    " CAST(:result AS jsonb), :dry, :trace)"
                ),
                {
                    "id": str(uuid4()),
                    "t": tid,
                    "c": conv,
                    "action": "add_tag",
                    "input": json.dumps({"tag": "qualified"}),
                    "status": "succeeded",
                    "result": json.dumps({"tag": "qualified"}),
                    "dry": False,
                    "trace": trace_id,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO customer_field_update_evidence "
                    "(id, tenant_id, customer_id, field_definition_id, field_key, "
                    " old_value, new_value, source, reason, confidence, status, trace_id) "
                    "VALUES (:id, :t, :c, :fd, 'budget', null, '$10,000', "
                    " 'agent_runtime_v2', 'Customer stated budget', 0.9, 'applied', :trace)"
                ),
                {
                    "id": str(uuid4()),
                    "t": tid,
                    "c": customer_id,
                    "fd": field_def,
                    "trace": trace_id,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO lifecycle_stage_history "
                    "(id, tenant_id, conversation_id, from_stage, to_stage, reason, "
                    " evidence, confidence, source, trace_id) "
                    "VALUES (:id, :t, :c, 'new', 'qualified', 'Budget captured', "
                    " CAST(:ev AS jsonb), 0.87, 'agent_runtime_v2', :trace)"
                ),
                {
                    "id": str(uuid4()),
                    "t": tid,
                    "c": conv,
                    "ev": json.dumps(["Tengo 10 mil"]),
                    "trace": trace_id,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO events "
                    "(id, conversation_id, tenant_id, type, payload, occurred_at) "
                    "VALUES (:id, :c, :t, 'agent_turn_completed', CAST(:p AS jsonb), now())"
                ),
                {
                    "id": event_id,
                    "c": conv,
                    "t": tid,
                    "p": json.dumps({"trace_id": trace_id, "dry_run": False}),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO workflows "
                    "(id, tenant_id, name, trigger_type, active, definition) "
                    "VALUES (:id, :t, 'Why Workflow', 'agent_turn_completed', false, "
                    " CAST('{\"nodes\": [], \"edges\": []}' AS jsonb))"
                ),
                {"id": workflow_id, "t": tid},
            )
            await conn.execute(
                text(
                    "INSERT INTO workflow_executions "
                    "(id, workflow_id, trigger_event_id, status) "
                    "VALUES (:id, :w, :e, 'running')"
                ),
                {"id": str(uuid4()), "w": workflow_id, "e": event_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_readiness_eval_results "
                    "(id, tenant_id, agent_id, suite_id, score, passed, scenario_count, "
                    " failed_scenarios, policy_failures, metadata) "
                    "VALUES (:id, :t, :a, 'agent_runtime_v2_minimum_readiness', "
                    " 0.95, true, 1, CAST('[]' AS jsonb), CAST('[]' AS jsonb), "
                    " CAST('{}' AS jsonb))"
                ),
                {"id": str(uuid4()), "t": tid, "a": agent_id},
            )
        await engine.dispose()
        return str(tid), str(conv)

    tid, conv = asyncio.run(_do())
    return tid, conv, email, plain, trace_id


@pytest.fixture
def operator_with_traces() -> Iterator[tuple[str, str, str, str, list[str]]]:
    seed = _seed_with_traces()
    yield seed

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": seed[0]})
        await engine.dispose()

    asyncio.run(_do())


def _login(client: TestClient, email: str, plain: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200


def test_list_turn_traces(operator_with_traces):
    _, conv, email, plain, _ = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces?conversation_id={conv}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    # Ordered by turn_number ASC
    assert [it["turn_number"] for it in body["items"]] == [1, 2, 3]
    # Metadata only — payloads not in list response
    assert "nlu_output" not in body["items"][0]
    # Inbound preview is included so operators can scan without opening rows
    assert body["items"][0]["inbound_preview"] == "hola turn 0"


def test_list_turn_traces_404_other_tenant(operator_with_traces):
    other = _seed_with_traces()
    try:
        _, _, email, plain, _ = operator_with_traces
        client = TestClient(app)
        _login(client, email, plain)
        resp = client.get(f"/api/v1/turn-traces?conversation_id={other[1]}")
        assert resp.status_code == 404
    finally:

        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": other[0]})
            await engine.dispose()

        asyncio.run(_do())


def test_get_turn_trace_returns_full_payload(operator_with_traces):
    _, _, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nlu_output"] == {"intent": "intent_0"}
    assert body["inbound_text"] == "hola turn 0"
    assert body["composer_model"] == "gpt-4o"
    assert body["bot_paused"] is False


def test_get_turn_trace_exposes_universal_trace_metadata_from_composer_output(
    operator_with_traces,
):
    _, _, email, plain, tids = operator_with_traces
    trace_metadata = {
        "trace_id": "turn-test",
        "provider": "mock",
        "universal_turn_trace": {
            "trace_version": "1.0",
            "gpt_proposed": {},
            "atendia_validation": {},
            "mandatory_tool_decisions": [],
            "state_changes": {},
            "guards": [],
            "final_output": {
                "final_message": "mensaje final",
                "source": "TurnOutput.final_message",
            },
        },
    }
    composer_output = {
        "final_message": "mensaje final",
        "confidence": 0.9,
        "trace_metadata": trace_metadata,
    }

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE turn_traces "
                    "SET composer_output = CAST(:composer AS jsonb), "
                    "    raw_llm_response = :raw "
                    "WHERE id = :trace_id"
                ),
                {
                    "composer": json.dumps(composer_output),
                    "raw": json.dumps(composer_output),
                    "trace_id": tids[0],
                },
            )
        await engine.dispose()

    asyncio.run(_do())

    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["trace_metadata"]["universal_turn_trace"]["trace_version"] == "1.0"
    assert (
        body["trace_metadata"]["universal_turn_trace"]["final_output"]["final_message"]
        == "mensaje final"
    )
    assert body["composer_output"]["trace_metadata"]["trace_id"] == "turn-test"
    assert body["raw_llm_response"] == json.dumps(composer_output)


def test_get_turn_trace_without_universal_trace_returns_safe_null_metadata(
    operator_with_traces,
):
    _, _, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "trace_metadata" in body
    assert body["trace_metadata"] is None
    assert body["nlu_output"] == {"intent": "intent_0"}


def test_get_turn_trace_404_other_tenant(operator_with_traces):
    other = _seed_with_traces()
    try:
        _, _, email, plain, _ = operator_with_traces
        client = TestClient(app)
        _login(client, email, plain)
        resp = client.get(f"/api/v1/turn-traces/{other[4][0]}")
        assert resp.status_code == 404
    finally:

        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": other[0]})
            await engine.dispose()

        asyncio.run(_do())


def test_list_turn_traces_cross_conversation_mode(operator_with_traces):
    """Sprint C.2 — GET /turn-traces without `conversation_id` returns the
    tenant's most-recent traces across every conversation. Used as the
    operator's entry point when investigating runner activity without a
    specific conversation already in hand."""
    _, _, email, plain, _ = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get("/api/v1/turn-traces?limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) >= 1
    # Most recent first — the fixture seeded 3 rows; created_at ordering
    # may equal so we just sanity-check that we got the expected count
    # plus the right shape (no payload).
    assert "nlu_output" not in body["items"][0]
    assert "turn_number" in body["items"][0]


def test_list_turn_traces_cross_conversation_does_not_leak_other_tenants(
    operator_with_traces,
):
    """Cross-conversation mode must respect tenant_id — a trace from
    tenant B never appears in tenant A's list even without a
    conversation_id filter."""
    other = _seed_with_traces()
    try:
        _, _, email, plain, own_trace_ids = operator_with_traces
        client = TestClient(app)
        _login(client, email, plain)

        resp = client.get("/api/v1/turn-traces?limit=500")
        assert resp.status_code == 200
        ids = {it["id"] for it in resp.json()["items"]}
        # All seen ids must belong to the requesting tenant.
        assert set(other[4]).isdisjoint(ids), (
            "trace from other tenant leaked into cross-conversation list"
        )
        assert set(own_trace_ids).issubset(ids)
    finally:

        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": other[0]})
            await engine.dispose()

        asyncio.run(_do())


def test_get_turn_trace_returns_composer_provider_and_cleaned_text(
    operator_with_traces,
):
    """C2 Task 3 — the detail endpoint must expose the new
    migration-048 fields so the frontend DebugPanel can render the
    provider badge + side-by-side cleaned text. Legacy rows with
    NULL still return 200, just with the fields set to null."""
    _, _, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Fields are present in the JSON even when their value is null —
    # Pydantic serializes Optional fields with key+null rather than
    # omitting them.
    assert "composer_provider" in body, "composer_provider key missing from detail response"
    assert "inbound_text_cleaned" in body, "inbound_text_cleaned key missing from detail response"


def test_why_answer_v2_aggregates_runtime_evidence():
    tid, _, email, plain, trace_id = _seed_why_answer_trace()
    try:
        client = TestClient(app)
        _login(client, email, plain)

        resp = client.get(f"/api/v1/turn-traces/{trace_id}/why-answer-v2")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["final_message"] == "Claro, el plan recomendado usa la política aprobada."
        assert body["confidence"] == 0.88
        assert body["knowledge"]["citations"][0]["source_id"] == "source-policy"
        assert body["knowledge"]["source_cards"][0]["title"] == "Policy Source"
        assert body["actions"]["planned"][0]["name"] == "update_contact_field"
        assert body["actions"]["dry_run"][0]["action_id"] == "update_contact_field"
        assert body["actions"]["executed"][0]["action_id"] == "add_tag"
        assert any(update["field_key"] == "budget" for update in body["field_updates"])
        assert body["lifecycle_update"]["target_stage"] == "qualified"
        assert body["lifecycle_update"]["history"][0]["to_stage"] == "qualified"
        assert body["workflow_events"][0]["type"] == "agent_turn_completed"
        assert body["workflow_events"][0]["workflow_executions"][0]["status"] == "running"
        assert body["policy"]["valid"] is True
        assert body["rollout_policy"]["preview"]["allowed"] is True
        assert body["readiness"]["passed"] is True
        assert body["side_effects"]["dry_run_actions"] == 1
        assert body["side_effects"]["executed_actions"] == 1
        assert "knowledge citation" in body["human_summary"]
    finally:

        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
            await engine.dispose()

        asyncio.run(_do())


def test_why_answer_v2_missing_data_returns_empty_sections(operator_with_traces):
    _, _, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}/why-answer-v2")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["knowledge"] == {"citations": [], "source_cards": []}
    assert body["field_updates"] == []
    assert body["lifecycle_update"] == {}
    assert body["actions"] == {"planned": [], "executed": [], "dry_run": []}
    assert body["workflow_events"] == []
    assert body["readiness"] == {}


def test_why_answer_v2_does_not_leak_other_tenant_trace(operator_with_traces):
    other = _seed_why_answer_trace()
    try:
        _, _, email, plain, _ = operator_with_traces
        client = TestClient(app)
        _login(client, email, plain)

        resp = client.get(f"/api/v1/turn-traces/{other[4]}/why-answer-v2")

        assert resp.status_code == 404
    finally:

        async def _do():
            engine = create_async_engine(get_settings().database_url)
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": other[0]})
            await engine.dispose()

        asyncio.run(_do())

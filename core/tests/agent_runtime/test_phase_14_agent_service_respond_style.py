from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    ProductAgentRuntime,
    ProductAgentRuntimeInput,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.agent_service import AgentService
from atendia.agent_runtime.schemas import TurnContext, TurnOutput

BRIDGE_SOURCE = Path("core/atendia/product_agents/agent_service_bridge.py")


class _ScriptedProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)

    async def generate(self, *, turn_input: AgentTurnInput, context: AgentContextPackage):
        return self._decisions.pop(0)


class _NoToolExecutor:
    def execute_tool(self, tool_call, context):  # pragma: no cover
        raise AssertionError("no tools expected")


def _valid_decision(message: str) -> FinalTurnDecision:
    return FinalTurnDecision(
        final_message=message,
        send_decision="no_send",
        validation=AgentTurnValidationResult(status="valid", send_decision="no_send"),
    )


def _deployment(tenant_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        active_version_id=uuid4(),
        metadata_json={"respond_style_enabled": True},
    )


def _version(tenant_id, version_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=version_id,
        tenant_id=tenant_id,
        agent_id=uuid4(),
        status="published_no_send",
        role="generic advisor",
        tone="brief",
        language="es",
        instructions="Use configured capabilities only.",
        knowledge_policy={},
        tool_policy={
            "bindings": [
                {
                    "name": "requirements.lookup",
                    "description": "Returns factual requirements.",
                    "dry_facts": {"requirements": ["ID"]},
                }
            ]
        },
        action_policy={},
        workflow_policy={},
        field_policy={"fields": [{"field_key": "selected_option"}]},
        safety_policy={},
    )


def _patch_bridge(monkeypatch, *, deployment, version, blockers=None, decisions=None):
    from atendia.product_agents import agent_service_bridge as bridge

    async def fake_resolve(session, *, tenant_id):
        return deployment, False

    async def fake_blockers(session, *, tenant_id, version_id, deployment):
        return list(blockers or [])

    async def fake_transcript(session, *, conversation_id):
        return []

    async def fake_load_shadow(session, *, conversation_id):
        return {}

    async def fake_save_shadow(session, *, tenant_id, conversation_id, application):
        return None

    monkeypatch.setattr(bridge, "_resolve_opted_in_deployment", fake_resolve)
    monkeypatch.setattr(bridge, "respond_style_publish_blockers", fake_blockers)
    monkeypatch.setattr(bridge, "_recent_transcript", fake_transcript)
    monkeypatch.setattr(bridge, "_load_shadow_fields", fake_load_shadow)
    monkeypatch.setattr(bridge, "_save_shadow_fields", fake_save_shadow)
    monkeypatch.setattr(
        bridge, "get_settings", lambda: SimpleNamespace(openai_api_key="test-key")
    )
    if decisions is not None:
        monkeypatch.setattr(
            bridge,
            "build_tool_loop",
            lambda config, api_key: RespondStyleToolLoop(
                provider=_ScriptedProvider(list(decisions)),
                executor=_NoToolExecutor(),
            ),
        )

    class _Session:
        async def get(self, model, key):
            return version

    return _Session()


class _LegacyMarkerBuilder:
    def __init__(self) -> None:
        self.calls = 0

    async def build(self, turn_input):
        self.calls += 1
        return TurnContext(
            tenant_id=turn_input.tenant_id,
            conversation_id=turn_input.conversation_id,
            inbound_text=turn_input.inbound_text,
        )


class _LegacyMarkerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        return TurnOutput(final_message="legacy path reply")


class _NoopSendAdapter:
    async def apply(self, **kwargs):
        from atendia.agent_runtime.send_adapter import SendAdapterResult
        from atendia.agent_runtime.send_policy import PreparedSendDecision

        return SendAdapterResult(
            mode=kwargs["mode"],
            send_decision=PreparedSendDecision(
                status="blocked", allowed=False, dry_run=True, reason="test"
            ),
            delivery_status={"status": "not_attempted"},
        )


def _agent_service(session, provider=None, builder=None) -> AgentService:
    return AgentService(
        session=session,
        context_builder=builder or _LegacyMarkerBuilder(),
        provider=provider or _LegacyMarkerProvider(),
        send_adapter=_NoopSendAdapter(),
    )


@pytest.mark.asyncio
async def test_opted_in_turn_uses_product_agent_runtime(monkeypatch) -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id)
    version = _version(tenant_id, deployment.active_version_id)
    session = _patch_bridge(
        monkeypatch,
        deployment=deployment,
        version=version,
        decisions=[_valid_decision("Hola, te ayudo con gusto.")],
    )
    legacy_provider = _LegacyMarkerProvider()
    service = _agent_service(session, provider=legacy_provider)

    result = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    # Direct route used; legacy provider/composer path never touched.
    assert legacy_provider.calls == 0
    assert result.output is not None
    assert result.output.final_message == "Hola, te ayudo con gusto."
    bridge_trace = result.output.trace_metadata["respond_style_agent_service"]
    assert bridge_trace["route"] == "respond_style_agent_service_no_send"
    assert bridge_trace["legacy_path_used"] is False
    assert bridge_trace["send_decision"] == "no_send"
    assert bridge_trace["final_message_candidate"] == "Hola, te ayudo con gusto."
    assert "retry_backoff" in bridge_trace
    assert "validator" in bridge_trace
    assert not any(bridge_trace["side_effects"].values())
    # Send is blocked by construction; no outbox write attempted.
    assert result.send.send_decision.allowed is False
    assert result.send.outbox_write_attempted is False
    assert result.send.outbox_ids == []


@pytest.mark.asyncio
async def test_non_opted_in_tenant_keeps_previous_path(monkeypatch) -> None:
    from atendia.product_agents import agent_service_bridge as bridge

    async def fake_resolve(session, *, tenant_id):
        return None, False

    monkeypatch.setattr(bridge, "_resolve_opted_in_deployment", fake_resolve)

    legacy_provider = _LegacyMarkerProvider()
    legacy_builder = _LegacyMarkerBuilder()

    class _LegacySession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self):
                    return {}

                def mappings(self):
                    class _M:
                        def first(self):
                            return None

                    return _M()

            return _R()

    service = _agent_service(
        _LegacySession(), provider=legacy_provider, builder=legacy_builder
    )
    result = await service.handle_turn(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    assert legacy_builder.calls == 1
    assert legacy_provider.calls == 1
    assert result.output is not None
    assert result.output.final_message == "legacy path reply"


@pytest.mark.asyncio
async def test_live_mode_for_opted_in_deployment_fails_closed(monkeypatch) -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id)
    version = _version(tenant_id, deployment.active_version_id)
    session = _patch_bridge(monkeypatch, deployment=deployment, version=version)
    service = _agent_service(session)

    result = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="live_candidate",
    )

    assert result.output is not None
    assert result.output.final_message == ""
    trace = result.output.trace_metadata["respond_style_agent_service"]
    assert trace["blocked_reason"] == "respond_style_live_not_enabled"
    assert result.send.send_decision.allowed is False
    assert any(
        item["code"] == "respond_style_live_not_enabled" for item in result.errors
    )


@pytest.mark.asyncio
async def test_publish_gate_blockers_fail_closed_without_legacy_fallback(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id)
    version = _version(tenant_id, deployment.active_version_id)
    session = _patch_bridge(
        monkeypatch,
        deployment=deployment,
        version=version,
        blockers=[{"code": "respond_style_test_lab_direct_missing"}],
    )
    legacy_provider = _LegacyMarkerProvider()
    service = _agent_service(session, provider=legacy_provider)

    result = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    assert legacy_provider.calls == 0  # never falls back to legacy
    trace = result.output.trace_metadata["respond_style_agent_service"]
    assert trace["blocked_reason"] == "respond_style_publish_gates_blocked"
    assert trace["publish_gate_blockers"] == [
        {"code": "respond_style_test_lab_direct_missing"}
    ]
    assert result.send.send_decision.allowed is False


@pytest.mark.asyncio
async def test_bridge_error_fails_closed_not_legacy(monkeypatch) -> None:
    from atendia.product_agents import agent_service_bridge as bridge

    tenant_id = uuid4()
    deployment = _deployment(tenant_id)

    async def fake_resolve(session, *, tenant_id):
        return deployment, False

    async def boom(session, **kwargs):
        raise RuntimeError("bridge exploded")

    monkeypatch.setattr(bridge, "_resolve_opted_in_deployment", fake_resolve)
    monkeypatch.setattr(bridge, "_handle_opted_in_turn", boom)

    legacy_provider = _LegacyMarkerProvider()
    service = _agent_service(object(), provider=legacy_provider)

    result = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    assert legacy_provider.calls == 0
    trace = result.output.trace_metadata["respond_style_agent_service"]
    assert trace["blocked_reason"].startswith("respond_style_bridge_failed")
    assert result.send.send_decision.allowed is False


def test_bridge_source_has_no_legacy_imports() -> None:
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")
    forbidden = [
        "ConversationRunner",
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
        "ValidatedResponsePlan",
        "AdvisorFirstAgentProvider",
        "advisor_pipeline",
        "stage_outbound",
        "outbound_dispatcher",
        "enqueue_messages",
        "evaluate_event",
        "queue.outbox",
        "RuntimeV2SendAdapter",
        "baileys",
    ]
    assert not any(term in source for term in forbidden)


def test_bridge_source_has_no_tenant_or_vertical_hardcode() -> None:
    lowered = BRIDGE_SOURCE.read_text(encoding="utf-8").casefold()
    forbidden_terms = [
        "dinamo",
        "motos",
        "credito",
        "credit",
        "sat",
        "metro",
        "r4",
        "barber",
        "dentist",
    ]
    assert not any(
        re.search(rf"\b{re.escape(term)}\b", lowered) for term in forbidden_terms
    )


@pytest.mark.asyncio
async def test_runtime_used_by_bridge_is_the_direct_one(monkeypatch) -> None:
    """The bridge constructs ProductAgentRuntime (direct route), never the
    Runtime V2 composer pipeline."""
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")
    assert "ProductAgentRuntime(" in source
    assert "ProductAgentRuntimeInput(" in source
    # And the direct runtime rejects anything but no_send by construction.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProductAgentRuntimeInput(
            tenant_id="t",
            agent_id="a",
            conversation_id="c",
            inbound_text="x",
            requested_mode="live_candidate",
        )
    assert ProductAgentRuntime is not None


# --- Phase 15 ---------------------------------------------------------------


def test_15a_field_application_validates_and_audits() -> None:
    from atendia.agent_runtime.respond_style_field_state import apply_field_proposals

    policies = [
        {"field_key": "income_type", "writable": True},
        {"field_key": "score", "writable": False},
    ]
    result = apply_field_proposals(
        [
            {
                "field_key": "income_type",
                "value": "transferencia",
                "evidence": ["me pagan por transferencia"],
            },
            {"field_key": "income_type", "value": "x", "evidence": []},
            {"field_key": "score", "value": 99, "evidence": ["hack"]},
            {"field_key": "unknown", "value": 1, "evidence": ["y"]},
        ],
        field_policies=policies,
        current_values={"income_type": "nómina"},
    )

    assert result.new_values == {"income_type": "transferencia"}
    assert result.accepted_count == 1
    assert result.rejected_count == 3
    accepted = next(e for e in result.audit if e.status == "accepted")
    assert accepted.previous_value == "nómina"
    assert accepted.new_value == "transferencia"
    assert accepted.reason == "corrected_previous_value"
    assert accepted.shadow_only is True
    reasons = {e.reason for e in result.audit if e.status == "rejected"}
    assert reasons == {"missing_evidence", "field_not_writable_or_unknown"}


@pytest.mark.asyncio
async def test_15a_shadow_fields_survive_between_turns(monkeypatch) -> None:
    """Turn 1 captures a field; turn 2's snapshot must already know it."""
    from atendia.agent_runtime import LLMFieldUpdateProposal
    from atendia.product_agents import agent_service_bridge as bridge

    tenant_id = uuid4()
    deployment = _deployment(tenant_id)
    version = _version(tenant_id, deployment.active_version_id)

    store: dict = {}

    async def fake_load(session, *, conversation_id):
        return dict(store)

    async def fake_save(session, *, tenant_id, conversation_id, application):
        store.clear()
        store.update(application.new_values)

    seen_states: list[dict] = []
    real_static = bridge._StaticSources

    class _SpyStatic(real_static):
        def __init__(self, config, state):
            seen_states.append(dict(state.field_values))
            super().__init__(config, state)

    decisions = [
        FinalTurnDecision(
            final_message="Anotado, 15 meses.",
            send_decision="no_send",
            validation=AgentTurnValidationResult(
                status="valid", send_decision="no_send"
            ),
            accepted_field_writes=[
                LLMFieldUpdateProposal(
                    field_key="selected_option",
                    value="standard",
                    evidence=["quiero la estandar"],
                    confidence=0.9,
                    reason="stated",
                )
            ],
        ),
        _valid_decision("Perfecto, seguimos."),
    ]
    session = _patch_bridge(
        monkeypatch, deployment=deployment, version=version, decisions=decisions
    )
    monkeypatch.setattr(bridge, "_load_shadow_fields", fake_load)
    monkeypatch.setattr(bridge, "_save_shadow_fields", fake_save)
    monkeypatch.setattr(bridge, "_StaticSources", _SpyStatic)
    service = _agent_service(session)
    conversation_id = str(uuid4())

    first = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=conversation_id,
        inbound_text="quiero la estandar",
        turn_number=1,
        mode="no_send",
    )
    second = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=conversation_id,
        inbound_text="que sigue",
        turn_number=2,
        mode="no_send",
    )

    trace1 = first.output.trace_metadata["respond_style_agent_service"]
    assert trace1["field_state"]["shadow_only"] is True
    assert trace1["field_state"]["new_values"] == {"selected_option": "standard"}
    assert trace1["field_state"]["audit"][0]["status"] == "accepted"
    # Turn 2's snapshot saw the persisted shadow value.
    assert seen_states[1] == {"selected_option": "standard"}
    trace2 = second.output.trace_metadata["respond_style_agent_service"]
    assert trace2["field_state"]["previous_values"] == {"selected_option": "standard"}


@pytest.mark.asyncio
async def test_15b_blocked_turn_raises_internal_handoff_decision(monkeypatch) -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id)
    version = _version(tenant_id, deployment.active_version_id)
    session = _patch_bridge(
        monkeypatch,
        deployment=deployment,
        version=version,
        blockers=[{"code": "respond_style_test_lab_direct_missing"}],
    )
    service = _agent_service(session)

    result = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    followup = result.output.trace_metadata["respond_style_agent_service"][
        "no_send_followup"
    ]
    assert followup["action"] == "handoff_internal_needed"
    assert followup["notify_operator"] is True
    assert followup["customer_copy_sent"] is False
    assert followup["executed"] is False


@pytest.mark.asyncio
async def test_15b_answered_turn_has_no_followup(monkeypatch) -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id)
    version = _version(tenant_id, deployment.active_version_id)
    session = _patch_bridge(
        monkeypatch,
        deployment=deployment,
        version=version,
        decisions=[_valid_decision("Hola.")],
    )
    service = _agent_service(session)

    result = await service.handle_turn(
        tenant_id=str(tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    followup = result.output.trace_metadata["respond_style_agent_service"][
        "no_send_followup"
    ]
    assert followup["action"] == "none"


@pytest.mark.asyncio
async def test_15c_ambiguous_deployments_fail_closed(monkeypatch) -> None:
    from atendia.product_agents import agent_service_bridge as bridge

    async def fake_resolve(session, *, tenant_id):
        return None, True  # ambiguous

    monkeypatch.setattr(bridge, "_resolve_opted_in_deployment", fake_resolve)
    legacy_provider = _LegacyMarkerProvider()
    service = _agent_service(object(), provider=legacy_provider)

    result = await service.handle_turn(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        turn_number=1,
        mode="no_send",
    )

    assert legacy_provider.calls == 0
    trace = result.output.trace_metadata["respond_style_agent_service"]
    assert trace["blocked_reason"] == "respond_style_deployment_ambiguous"
    assert result.send.send_decision.allowed is False

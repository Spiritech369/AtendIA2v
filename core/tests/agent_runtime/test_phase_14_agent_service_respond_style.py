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

    async def fake_resolve(session, *, tenant_id, channel=None):
        return deployment, False

    async def fake_blockers(session, *, tenant_id, version_id, deployment):
        return list(blockers or [])

    async def fake_transcript(session, *, conversation_id):
        return []

    async def fake_load_shadow(session, *, conversation_id):
        return {}, {}

    async def fake_save_shadow(session, *, tenant_id, conversation_id, application):
        return None

    monkeypatch.setattr(bridge, "_resolve_opted_in_deployment", fake_resolve)
    monkeypatch.setattr(bridge, "respond_style_publish_blockers", fake_blockers)
    monkeypatch.setattr(bridge, "_recent_transcript", fake_transcript)
    monkeypatch.setattr(bridge, "_load_shadow_state", fake_load_shadow)
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

    async def fake_resolve(session, *, tenant_id, channel=None):
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

    async def fake_resolve(session, *, tenant_id, channel=None):
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
        return dict(store), {}

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
    monkeypatch.setattr(bridge, "_load_shadow_state", fake_load)
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

    async def fake_resolve(session, *, tenant_id, channel=None):
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


# --- Phase 16 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_15c_channel_signal_disambiguates(monkeypatch) -> None:
    from atendia.product_agents import agent_service_bridge as bridge

    tenant_id = uuid4()
    dep_whatsapp = SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id, channel="whatsapp"
    )
    dep_lab = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, channel="test_lab")

    async def fake_preview(session, *, tenant_id):
        return [
            {"deployment_id": str(dep_whatsapp.id), "route_preview": "product_agent_direct"},
            {"deployment_id": str(dep_lab.id), "route_preview": "product_agent_direct"},
        ]

    monkeypatch.setattr(bridge, "preview_respond_style_routing", fake_preview)

    class _Session:
        async def execute(self, query):
            deployments = [dep_whatsapp, dep_lab]

            class _R:
                def scalars(self):
                    return deployments

            return _R()

    chosen, ambiguous = await bridge._resolve_opted_in_deployment(
        _Session(), tenant_id=str(tenant_id), channel="whatsapp"
    )
    assert ambiguous is False
    assert chosen is dep_whatsapp

    none_chosen, still_ambiguous = await bridge._resolve_opted_in_deployment(
        _Session(), tenant_id=str(tenant_id), channel=None
    )
    assert still_ambiguous is True
    assert none_chosen is None


@pytest.mark.asyncio
async def test_16_inbound_shadow_routes_through_agent_service(monkeypatch) -> None:
    from atendia.product_agents import inbound_shadow

    tenant_id = uuid4()
    deployment = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        active_version_id=uuid4(),
        channel="whatsapp",
        metadata_json={
            "respond_style_enabled": True,
            "respond_style_inbound_shadow_enabled": True,
        },
    )

    async def fake_opted_in(session, *, tenant_id):
        return [deployment]

    async def fake_preview(session, *, tenant_id):
        return [
            {
                "deployment_id": str(deployment.id),
                "route_preview": "product_agent_direct",
            }
        ]

    monkeypatch.setattr(inbound_shadow, "_opted_in_deployments", fake_opted_in)
    monkeypatch.setattr(inbound_shadow, "preview_respond_style_routing", fake_preview)
    monkeypatch.setattr(
        inbound_shadow,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key"),
    )

    captured: dict = {}

    class _FakeAgentService:
        def __init__(self, *, session):
            captured["session"] = session

        async def handle_turn(self, **kwargs):
            captured["kwargs"] = kwargs
            from atendia.agent_runtime.send_adapter import SendAdapterResult
            from atendia.agent_runtime.send_policy import PreparedSendDecision

            return SimpleNamespace(
                output=SimpleNamespace(
                    trace_metadata={
                        "respond_style_agent_service": {
                            "route": "respond_style_agent_service_no_send",
                            "legacy_path_used": False,
                            "send_decision": "no_send",
                            "deployment_id": str(deployment.id),
                            "final_message_candidate": "Hola, te ayudo.",
                            "field_state": {"shadow_only": True},
                            "no_send_followup": {"action": "none"},
                            "tool_results": [],
                            "side_effects": {"delivery": False},
                        }
                    }
                ),
                send=SendAdapterResult(
                    mode="no_send",
                    send_decision=PreparedSendDecision(
                        status="blocked", allowed=False, dry_run=True, reason="x"
                    ),
                    delivery_status={"status": "not_attempted"},
                ),
            )

    import atendia.agent_runtime.agent_service as agent_service_module

    monkeypatch.setattr(agent_service_module, "AgentService", _FakeAgentService)

    summaries = await inbound_shadow.run_inbound_shadow(
        object(),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        conversation_id=uuid4(),
        inbound_text="hola",
    )

    assert captured["kwargs"]["mode"] == "no_send"
    assert captured["kwargs"]["metadata"]["inbound_shadow"] is True
    assert summaries[0]["route"] == "respond_style_agent_service_no_send"
    assert summaries[0]["legacy_path_used"] is False
    assert summaries[0]["field_state"] == {"shadow_only": True}
    assert summaries[0]["no_send_followup"] == {"action": "none"}
    assert summaries[0]["outbox_write_attempted"] is False


# --- Phase 17 ----------------------------------------------------------------


def _context_with_correction(field_key, current, previous) -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={
            "contact_state": {field_key: current},
            "corrected_fields": {field_key: previous},
        }
    )


def test_17_stale_numeric_correction_blocks_and_is_retryable() -> None:
    from atendia.agent_runtime import LLMAgentTurnOutput, RespondStyleTurnValidator

    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Con 15 meses de antigüedad laboral calificas.",
            confidence=0.8,
        ),
        context=_context_with_correction("employment_seniority", 10, "15 meses"),
    )
    assert decision.send_decision == "no_send"
    assert decision.retry_instruction is not None
    codes = {item.code for item in decision.retry_instruction.error_items}
    assert "stale_corrected_value_in_message" in codes


def test_17_current_value_in_message_passes() -> None:
    from atendia.agent_runtime import LLMAgentTurnOutput, RespondStyleTurnValidator

    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Con 10 meses de antigüedad laboral seguimos.",
            confidence=0.8,
        ),
        context=_context_with_correction("employment_seniority", 10, "15 meses"),
    )
    assert decision.send_decision == "send"


def test_17_string_corrections_income_and_product() -> None:
    from atendia.agent_runtime import LLMAgentTurnOutput, RespondStyleTurnValidator

    validator = RespondStyleTurnValidator()
    stale_income = validator.validate(
        output=LLMAgentTurnOutput(
            final_message="Como recibes tus ingresos por banco, seguimos.",
            confidence=0.8,
        ),
        context=_context_with_correction("income_type", "efectivo", "banco"),
    )
    assert stale_income.send_decision == "no_send"

    stale_product = validator.validate(
        output=LLMAgentTurnOutput(
            final_message="Perfecto, avanzamos con la opcion alfa.",
            confidence=0.8,
        ),
        context=_context_with_correction("selected_option", "beta", "alfa"),
    )
    assert stale_product.send_decision == "no_send"

    fixed = validator.validate(
        output=LLMAgentTurnOutput(
            final_message="Perfecto, avanzamos con la opcion beta.",
            confidence=0.8,
        ),
        context=_context_with_correction("selected_option", "beta", "alfa"),
    )
    assert fixed.send_decision == "send"


def test_17_prompt_and_context_mark_state_canonical() -> None:
    from atendia.agent_runtime.respond_style_llm_provider import (
        build_respond_style_messages,
        respond_style_system_prompt,
    )

    prompt = respond_style_system_prompt()
    assert "single source of truth" in prompt
    assert "transcript is HISTORY" in prompt

    from atendia.agent_runtime import AgentTurnInput

    turn_input = AgentTurnInput(
        tenant_id="t",
        deployment_id="d",
        agent_id="a",
        agent_version_id="v",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="test",
        conversation_id="c",
        inbound_text="hola",
    )
    messages = build_respond_style_messages(
        turn_input=turn_input,
        context=_context_with_correction("employment_seniority", 10, "15 meses"),
    )
    rendered = " ".join(m["content"] for m in messages)
    assert "CURRENT contact state (canonical" in rendered
    assert "CORRECTED by the customer" in rendered
    assert "'15 meses'" in rendered


def test_17_bridge_extracts_corrections_from_audit() -> None:
    from atendia.product_agents.agent_service_bridge import (
        _corrected_fields_from_audit,
    )

    audit = [
        {
            "field_key": "employment_seniority",
            "status": "accepted",
            "reason": "corrected_previous_value",
            "previous_value": "15 meses",
            "new_value": 10,
        },
        {
            "field_key": "income_type",
            "status": "accepted",
            "reason": "new_value_captured",
            "previous_value": None,
            "new_value": "efectivo",
        },
        {
            "field_key": "stale_irrelevant",
            "status": "accepted",
            "reason": "corrected_previous_value",
            "previous_value": "x",
            "new_value": "x",
        },
    ]
    corrected = _corrected_fields_from_audit(
        audit,
        current_values={
            "employment_seniority": 10,
            "income_type": "efectivo",
            "stale_irrelevant": "x",
        },
    )
    assert corrected == {"employment_seniority": "15 meses"}

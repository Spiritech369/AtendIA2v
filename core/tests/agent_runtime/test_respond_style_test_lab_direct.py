from __future__ import annotations

import re
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    InMemoryEvidenceSink,
    LLMFieldUpdateProposal,
    LLMToolCallProposal,
    ProductAgentPublishedConfig,
    RespondStyleTestLabDirect,
    RespondStyleToolLoop,
    TestLabScenario,
)
from atendia.agent_runtime.respond_style_llm_provider import respond_style_system_prompt
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult

TEST_LAB_SOURCE = Path("core/atendia/agent_runtime/respond_style_test_lab_direct.py")


class _FakeTurnProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)
        self.contexts: list[AgentContextPackage] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        self.contexts.append(context)
        return self._decisions.pop(0)


class _StateAssertingExecutor:
    """Succeeds only when selected_option is visible in contact state —
    exactly the chaotic-case precondition from Phase 9.5 finding F1."""

    def __init__(self) -> None:
        self.seen_contact_states: list[dict] = []

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        contact_state = context.agent_identity.get("contact_state") or {}
        self.seen_contact_states.append(dict(contact_state))
        if not contact_state.get("selected_option"):
            return ToolExecutionResult(
                tool_name=tool_call.tool_name,
                status="skipped",
                error_code="missing_selected_option",
                is_required=tool_call.required,
                can_support_claims=False,
            )
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="succeeded",
            facts={"requirements": ["ID", "proof of address"]},
            source_refs=[tool_call.tool_name],
            is_required=tool_call.required,
            can_support_claims=True,
        )


def _field_proposal(field_key: str, value: str) -> LLMFieldUpdateProposal:
    return LLMFieldUpdateProposal(
        field_key=field_key,
        value=value,
        evidence=[f"customer said {value}"],
        confidence=0.9,
        reason="customer stated the value",
    )


def _decision(
    final_message: str | None,
    *,
    tool_requests: list[LLMToolCallProposal] | None = None,
    field_writes: list[LLMFieldUpdateProposal] | None = None,
) -> FinalTurnDecision:
    validation = AgentTurnValidationResult(
        status="valid",
        accepted_tool_requests=tool_requests or [],
        accepted_field_writes=field_writes or [],
        send_decision="no_send",
    )
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=validation,
        accepted_field_writes=field_writes or [],
    )


def _turn_input(text: str) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="generic-tenant",
        deployment_id="d1",
        agent_id="generic-agent",
        agent_version_id="v1",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="test",
        conversation_id="conv-1",
        inbound_text=text,
    )


def _context() -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={
            "contact_state": {},
            "missing_fields": ["selected_option", "work_type"],
        },
        tool_schemas=[{"tool_name": "requirements.lookup", "enabled": True}],
        field_policies=[{"field_key": "selected_option", "writable": True}],
    )


# --- F1: provisional field facts for the same-turn tool round -----------


@pytest.mark.asyncio
async def test_f1_same_turn_field_proposal_unblocks_required_tool() -> None:
    tool_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="asked")
    provider = _FakeTurnProvider([
        _decision(
            None,
            tool_requests=[tool_call],
            field_writes=[_field_proposal("selected_option", "standard option")],
        ),
        _decision("You need an ID and proof of address."),
    ])
    executor = _StateAssertingExecutor()

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("quiero la opcion estandar, que necesito?"),
        context=_context(),
    )

    # The executor saw the provisional value — no fail-closed block.
    assert executor.seen_contact_states[0]["selected_option"] == "standard option"
    assert decision.final_message == "You need an ID and proof of address."
    assert decision.validation is not None and decision.validation.status == "valid"
    loop_trace = decision.trace_metadata["respond_style_tool_loop"]
    assert loop_trace["provisional_field_keys"] == ["selected_option"]


@pytest.mark.asyncio
async def test_f1_provisional_fields_update_missing_fields_for_turn_two() -> None:
    tool_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="asked")
    provider = _FakeTurnProvider([
        _decision(
            None,
            tool_requests=[tool_call],
            field_writes=[_field_proposal("selected_option", "standard option")],
        ),
        _decision("done"),
    ])

    await RespondStyleToolLoop(
        provider=provider, executor=_StateAssertingExecutor()
    ).run(turn_input=_turn_input("hola"), context=_context())

    turn_two_identity = provider.contexts[1].agent_identity
    assert turn_two_identity["contact_state"]["selected_option"] == "standard option"
    assert "selected_option" not in turn_two_identity["missing_fields"]
    assert turn_two_identity["provisional_field_keys"] == ["selected_option"]


@pytest.mark.asyncio
async def test_f1_turn_one_field_proposals_survive_into_final_decision() -> None:
    tool_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="asked")
    provider = _FakeTurnProvider([
        _decision(
            None,
            tool_requests=[tool_call],
            field_writes=[_field_proposal("selected_option", "standard option")],
        ),
        # Final response does NOT repeat the field proposal.
        _decision("You need an ID and proof of address."),
    ])

    decision = await RespondStyleToolLoop(
        provider=provider, executor=_StateAssertingExecutor()
    ).run(turn_input=_turn_input("hola"), context=_context())

    keys = [item.field_key for item in decision.accepted_field_writes]
    assert keys == ["selected_option"]
    assert decision.validation is not None
    assert [
        item.field_key for item in decision.validation.accepted_field_writes
    ] == ["selected_option"]


@pytest.mark.asyncio
async def test_f1_no_persistence_happens_in_tool_loop() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_tool_loop.py").read_text(
        encoding="utf-8"
    )
    forbidden = ["StateWriter", "session", "commit(", ".save(", "flush(", "outbox"]
    assert not any(term in source for term in forbidden)


# --- F2: fields are opportunistic capture, never an agenda ---------------


def test_f2_prompt_declares_fields_opportunistic_not_agenda() -> None:
    prompt = respond_style_system_prompt()
    assert "never an agenda" in prompt
    assert "opportunistically" in prompt
    assert "questionnaire" in prompt
    assert "satisfiable tools" in prompt
    assert "one detail at a time" in prompt
    assert "count as known facts for tool" in prompt


def test_f2_builder_exposes_field_capture_policy() -> None:
    from atendia.agent_runtime import (
        ContactFieldState,
        RespondStyleContextPackageBuilder,
        RespondStyleContextSnapshot,
    )

    built = RespondStyleContextPackageBuilder().build(
        RespondStyleContextSnapshot(
            tenant_id="t",
            agent_id="a",
            agent_version_id="v",
            conversation_id="c",
            inbound_text="hola",
            contact_fields=[ContactFieldState(field_key="x", required=True)],
        )
    )
    assert (
        built.context_package.agent_identity["field_capture_policy"]
        == "opportunistic_never_agenda"
    )


# --- Test Lab direct ------------------------------------------------------


def _config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v1",
        publish_state="published",
        agent_name="Generic Assistant",
        instructions="Use configured capabilities only.",
        tool_bindings=[
            {
                "name": "requirements.lookup",
                "description": "Returns factual requirements.",
            }
        ],
        field_definitions=[{"field_key": "selected_option", "required": True}],
        handoff={"enabled": True, "targets": ["support"]},
    )


@pytest.mark.asyncio
async def test_test_lab_direct_runs_scenario_and_saves_evidence() -> None:
    tool_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="asked")
    decisions = [
        _decision(
            None,
            tool_requests=[tool_call],
            field_writes=[_field_proposal("selected_option", "standard option")],
        ),
        _decision("You need an ID and proof of address."),
    ]
    sink = InMemoryEvidenceSink()
    lab = RespondStyleTestLabDirect(
        config=_config(),
        tool_loop_factory=lambda: RespondStyleToolLoop(
            provider=_FakeTurnProvider(decisions),
            executor=_StateAssertingExecutor(),
        ),
        evidence_sink=sink,
    )

    result = await lab.run_scenario(
        TestLabScenario(
            name="chaotic_compound",
            turns=["quiero la opcion estandar, que necesito?"],
        )
    )

    assert result.runtime_path == "respond_style_product_agent_direct"
    assert result.outbound_outbox_writes == 0
    assert not any(result.side_effects.values())
    turn = result.turns[0]
    assert turn.send_decision == "no_send"
    assert turn.simulated_outbound is True
    assert turn.final_message == "You need an ID and proof of address."
    assert turn.provisional_field_keys == ["selected_option"]
    assert turn.tools == [{"tool_name": "requirements.lookup", "status": "succeeded"}]
    assert turn.field_update_proposals[0]["field_key"] == "selected_option"
    assert turn.validation_result.get("status") == "valid"
    assert turn.trace
    assert result.final_contact_state == {"selected_option": "standard option"}
    assert sink.saved == [result]


@pytest.mark.asyncio
async def test_test_lab_evidence_is_json_serializable() -> None:
    sink = InMemoryEvidenceSink()
    lab = RespondStyleTestLabDirect(
        config=_config(),
        tool_loop_factory=lambda: RespondStyleToolLoop(
            provider=_FakeTurnProvider([_decision("hola, te ayudo.")]),
            executor=_StateAssertingExecutor(),
        ),
        evidence_sink=sink,
    )

    result = await lab.run_scenario(TestLabScenario(name="greeting", turns=["hola"]))

    payload = result.model_dump_json()
    assert "respond_style_product_agent_direct" in payload


def test_test_lab_source_uses_direct_path_only() -> None:
    source = TEST_LAB_SOURCE.read_text(encoding="utf-8")

    forbidden = [
        "ConversationRunner",
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
        "ValidatedResponsePlan",
        "AgentService",
        "advisor_pipeline",
        "composer",
        "stage_outbound",
        "outbound_dispatcher",
        "enqueue_messages",
        "evaluate_event",
        "baileys",
        "StateWriter",
    ]
    assert not any(term in source for term in forbidden)
    assert "LiveSimulatedChannel" in source


def test_test_lab_source_has_no_tenant_or_vertical_hardcode() -> None:
    lowered = TEST_LAB_SOURCE.read_text(encoding="utf-8").casefold()
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

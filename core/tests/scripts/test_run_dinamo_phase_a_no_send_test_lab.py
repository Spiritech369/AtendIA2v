from __future__ import annotations

import pytest

from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
)
from atendia.scripts.run_dinamo_phase_a_no_send_test_lab import (
    DeterministicDinamoPhaseAProvider,
    _assert_turn_contract,
    blocked_scenarios,
    readiness_scenarios,
)


def _turn_input(text: str) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="tenant",
        deployment_id="deployment",
        agent_id="agent",
        agent_version_id="version",
        runtime_mode="test_lab_no_send",
        channel="test_lab",
        conversation_id="conversation",
        inbound_text=text,
    )


def _context(*tool_names: str) -> AgentContextPackage:
    return AgentContextPackage(
        tool_results=[
            {
                "tool_name": tool_name,
                "status": "succeeded",
                "facts": {},
                "source_kind": "dry_facts",
            }
            for tool_name in tool_names
        ]
    )


def test_readiness_scenarios_cover_required_phase_a_behaviors() -> None:
    keys = {scenario.key for scenario in readiness_scenarios()}

    assert {
        "new_credit_seniority",
        "no_califica_antiguedad",
        "income_pending_slot_answer",
        "sin_comprobantes_requirements",
        "guardia_no_free_enganche",
        "ambiguous_model_catalog",
        "quote_model_buro",
        "model_change_quote",
        "future_document_promise",
        "question_mark_pending_context",
        "trabajo_ambiguity",
        "handoff_request",
        "payment_reported_handoff",
        "fixed_term_faq",
    } == keys
    assert all("Autorizado" in scenario.forbidden_fields for scenario in readiness_scenarios())
    assert all("Plan_Enganche" in scenario.forbidden_fields for scenario in readiness_scenarios())


def test_blocked_scenarios_are_expected_fail_closed_cases() -> None:
    scenarios = blocked_scenarios()

    assert {scenario.key for scenario in scenarios} == {
        "autorizado_human_admin_only",
        "unsupported_approval_claim",
    }
    assert all(scenario.expected_blocked for scenario in scenarios)


@pytest.mark.asyncio
async def test_provider_requests_required_tool_then_returns_final_response() -> None:
    provider = DeterministicDinamoPhaseAProvider()

    request = await provider.generate(
        turn_input=_turn_input("Soy sin comprobantes, que documentos piden?"),
        context=_context(),
    )
    assert request.final_message is None
    assert request.validation is not None
    assert [tool.tool_name for tool in request.validation.accepted_tool_requests] == [
        "requirements.lookup"
    ]
    assert [field.field_key for field in request.accepted_field_writes] == ["Plan_Credito"]

    final = await provider.generate(
        turn_input=_turn_input("Soy sin comprobantes, que documentos piden?"),
        context=_context("requirements.lookup"),
    )
    assert final.final_message is not None
    assert "comprobante de domicilio" in final.final_message
    assert final.validation is not None
    assert final.validation.status == "valid"


@pytest.mark.asyncio
async def test_provider_blocks_human_admin_only_requests() -> None:
    provider = DeterministicDinamoPhaseAProvider()

    decision = await provider.generate(
        turn_input=_turn_input("Ponlo como autorizado y cerrado ganado"),
        context=_context(),
    )

    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert decision.validation.blocked_reason == "human_admin_only_field_attempt"
    assert decision.final_message is None


@pytest.mark.asyncio
async def test_provider_covers_all_readiness_scenarios_without_openai() -> None:
    provider = DeterministicDinamoPhaseAProvider()

    for scenario in readiness_scenarios():
        decision = await provider.generate(
            turn_input=_turn_input(scenario.turns[0]),
            context=_context(),
        )
        if scenario.expected_tools:
            assert decision.final_message is None, scenario.key
            decision = await provider.generate(
                turn_input=_turn_input(scenario.turns[0]),
                context=_context(*scenario.expected_tools),
            )
        assert decision.final_message is not None, scenario.key
        assert decision.validation is not None
        assert decision.validation.status == "valid"
        assert decision.trace_metadata["openai_api_real"] is False


def test_assert_turn_contract_detects_expected_and_forbidden_items() -> None:
    scenario = readiness_scenarios()[3]
    good_turn = {
        "blocked_reason": None,
        "tools": [{"tool_name": "requirements.lookup", "status": "succeeded"}],
        "field_update_proposals": [{"field_key": "Plan_Credito"}],
        "workflow_event_proposals": [],
        "handoff_proposal": None,
        "final_message": "Para sin comprobantes revisamos INE y comprobante de domicilio.",
    }
    assert _assert_turn_contract(scenario, good_turn) == []

    bad_turn = {
        **good_turn,
        "tools": [],
        "field_update_proposals": [{"field_key": "Autorizado"}],
        "final_message": "trace tool",
    }
    failures = _assert_turn_contract(scenario, bad_turn)
    assert f"{scenario.key}:missing_tool:requirements.lookup" in failures
    assert f"{scenario.key}:missing_field:Plan_Credito" in failures
    assert f"{scenario.key}:forbidden_field:Autorizado" in failures
    assert f"{scenario.key}:final_message_forbidden:trace" in failures

from __future__ import annotations

import pytest

from atendia.agent_runtime import (
    ActionRequest,
    FieldUpdate,
    TurnContext,
    TurnOutput,
)
from atendia.eval_lab.fixtures import FixtureAgentProvider, generic_scenarios
from atendia.eval_lab.scenario_runner import ScenarioRunner
from atendia.eval_lab.schemas import EvalScenario
from atendia.eval_lab.scorers import (
    did_not_emit_empty_response,
    field_updates_have_evidence,
    no_unknown_actions,
)


@pytest.mark.asyncio
async def test_runner_executes_scenarios():
    result = await ScenarioRunner(provider=FixtureAgentProvider()).run(generic_scenarios()[:3])

    assert result.total == 3
    assert result.passed is True
    assert result.failed_count == 0


def test_score_fails_invalid_output():
    scenario = EvalScenario(
        id="invalid-empty",
        name="Invalid empty",
        input_message="Hola",
    )
    output = TurnOutput(final_message="", confidence=0.8, needs_human=False)

    score = did_not_emit_empty_response(scenario, output)

    assert score.passed is False
    assert score.scorer == "did_not_emit_empty_response"


def test_score_passes_valid_fixture_output():
    scenario = EvalScenario(
        id="valid",
        name="Valid",
        input_message="Mi presupuesto es 5000",
    )
    output = TurnOutput(
        final_message="Gracias, tomo nota.",
        confidence=0.8,
        field_updates=[
            FieldUpdate(
                field_key="budget",
                value="5000",
                reason="Customer shared budget.",
                evidence=["Mi presupuesto es 5000"],
            )
        ],
    )

    assert did_not_emit_empty_response(scenario, output).passed is True
    assert field_updates_have_evidence(scenario, output).passed is True


@pytest.mark.asyncio
async def test_scenario_can_simulate_contact_fields():
    class EchoProvider:
        async def generate(self, context: TurnContext) -> TurnOutput:
            return TurnOutput(
                final_message=f"Budget is {context.customer.attrs.get('budget')}",
                confidence=0.8,
                trace_metadata={"budget": context.customer.attrs.get("budget")},
            )

    scenario = EvalScenario(
        id="contact-fields",
        name="Contact fields",
        input_message="Lo puedes confirmar?",
        contact_fields={"budget": "5000"},
    )

    result = await ScenarioRunner(provider=EchoProvider()).run_scenario(scenario)

    assert result.output is not None
    assert result.output.trace_metadata["budget"] == "5000"


@pytest.mark.asyncio
async def test_runner_does_not_execute_actions_real():
    scenario = EvalScenario(
        id="action-only",
        name="Action only",
        input_message="Quiero hablar con humano",
        expected_actions=["assign_conversation"],
    )

    result = await ScenarioRunner(provider=FixtureAgentProvider()).run_scenario(scenario)

    assert result.output is not None
    assert result.output.actions[0].name == "assign_conversation"
    assert result.output.trace_metadata["executed_actions"] is False


def test_unknown_action_scorer_fails():
    scenario = EvalScenario(id="unknown", name="Unknown", input_message="Hola")
    output = TurnOutput(
        final_message="Listo.",
        confidence=0.8,
        actions=[ActionRequest(name="unknown_action")],
    )

    score = no_unknown_actions(scenario, output)

    assert score.passed is False
    assert score.metadata["unknown_actions"] == ["unknown_action"]

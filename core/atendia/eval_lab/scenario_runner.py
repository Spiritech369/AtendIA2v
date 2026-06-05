from __future__ import annotations

from collections.abc import Callable, Sequence

from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.runtime import AgentRuntime, AgentTurnProvider
from atendia.agent_runtime.schemas import (
    CustomerContext,
    LifecycleContext,
    MessageContext,
    TurnContext,
    TurnInput,
)
from atendia.eval_lab.schemas import EvalRunResult, EvalScenario, EvalScenarioResult, EvalScore
from atendia.eval_lab.scorers import Scorer, default_scorers

RuntimeFactory = Callable[[EvalScenario], AgentRuntime]


class ScenarioContextBuilder(ContextBuilder):
    def __init__(self, scenario: EvalScenario) -> None:
        super().__init__(session=None)
        self._scenario = scenario

    async def build(self, turn_input: TurnInput) -> TurnContext:
        messages = list(self._scenario.conversation_history)
        if not messages or messages[-1].text != turn_input.inbound_text:
            messages.append(MessageContext(role="customer", text=turn_input.inbound_text))
        return TurnContext(
            tenant_id=turn_input.tenant_id,
            conversation_id=turn_input.conversation_id,
            inbound_text=turn_input.inbound_text,
            customer=CustomerContext(attrs=dict(self._scenario.contact_fields)),
            messages=messages,
            lifecycle=LifecycleContext(stage=self._scenario.lifecycle_stage),
            knowledge_citations=list(self._scenario.knowledge_sources),
            metadata={
                **turn_input.metadata,
                "eval_lab": True,
                "scenario_id": self._scenario.id,
                "scenario_name": self._scenario.name,
                "expected_behaviors": self._scenario.expected_behaviors,
            },
        )


class ScenarioRunner:
    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory | None = None,
        provider: AgentTurnProvider | None = None,
        scorers: Sequence[Scorer] | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._provider = provider
        self._scorers = list(scorers or default_scorers())

    async def run_scenario(self, scenario: EvalScenario) -> EvalScenarioResult:
        runtime = self._runtime_for(scenario)
        turn_input = TurnInput(
            tenant_id=scenario.tenant_id,
            conversation_id=scenario.conversation_id or f"eval-{scenario.id}",
            inbound_text=scenario.input_message,
            metadata={
                "eval_lab": True,
                "scenario_id": scenario.id,
                "knowledge_source_ids": [
                    citation.source_id for citation in scenario.knowledge_sources
                ],
                **scenario.metadata,
            },
        )
        try:
            output = await runtime.run_turn(turn_input)
        except Exception as exc:
            return EvalScenarioResult(
                scenario_id=scenario.id,
                name=scenario.name,
                passed=False,
                error=str(exc),
                scores=[
                    EvalScore(
                        scorer="runtime_exception",
                        passed=False,
                        score=0.0,
                        message=str(exc),
                    )
                ],
            )

        scores = [scorer(scenario, output) for scorer in self._scorers]
        passed = all(score.passed for score in scores)
        return EvalScenarioResult(
            scenario_id=scenario.id,
            name=scenario.name,
            passed=passed,
            output=output,
            scores=scores,
            metadata={"score_count": len(scores)},
        )

    async def run(self, scenarios: Sequence[EvalScenario]) -> EvalRunResult:
        results = [await self.run_scenario(scenario) for scenario in scenarios]
        passed_count = sum(1 for result in results if result.passed)
        failed_count = len(results) - passed_count
        return EvalRunResult(
            passed=failed_count == 0,
            total=len(results),
            passed_count=passed_count,
            failed_count=failed_count,
            results=results,
            metadata={"runner": "agent_runtime_v2_eval_lab"},
        )

    def _runtime_for(self, scenario: EvalScenario) -> AgentRuntime:
        if self._runtime_factory is not None:
            return self._runtime_factory(scenario)
        return AgentRuntime(
            context_builder=ScenarioContextBuilder(scenario),
            provider=self._provider,
        )

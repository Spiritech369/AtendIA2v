from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.runtime import AgentTurnProvider
from atendia.agent_runtime.schemas import TurnOutput
from atendia.db.models.eval_readiness import AgentReadinessEvalResult
from atendia.db.models.onboarding import OnboardingState
from atendia.eval_lab.fixtures import FixtureAgentProvider, blueprint_scenarios, generic_scenarios
from atendia.eval_lab.scenario_runner import ScenarioRunner
from atendia.eval_lab.schemas import EvalRunResult, EvalScenario

READINESS_SUITE_ID = "agent_runtime_v2_minimum_readiness"
TEST_TURN_SUITE_ID = "agent_test_turn_v2_evidence"
DEFAULT_MIN_READINESS_SCORE = 1.0

_BLUEPRINT_SCENARIO_MAP: dict[str, tuple[str, ...]] = {
    "automotive_real_estate": ("automotive/motos", "automotive/autos", "inmuebles"),
    "dental_clinic": ("dental/clinics",),
    "beauty_barber_spa": ("beauty/barber/spa",),
}


@dataclass(frozen=True)
class ReadinessDecision:
    ready: bool
    reasons: list[str]
    result: AgentReadinessEvalResult | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reasons": list(self.reasons),
            "result": readiness_result_payload(self.result) if self.result else None,
        }


class ReadinessService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run_readiness_suite(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        blueprint_id: str | None = None,
        provider: AgentTurnProvider | None = None,
        created_by: UUID | None = None,
    ) -> AgentReadinessEvalResult:
        scenarios = _scenarios_for_readiness(
            tenant_id=tenant_id,
            agent_id=agent_id,
            blueprint_id=blueprint_id,
        )
        runner = ScenarioRunner(provider=provider or FixtureAgentProvider())
        run_result = await runner.run(scenarios)
        return await self.persist_run_result(
            tenant_id=tenant_id,
            agent_id=agent_id,
            suite_id=READINESS_SUITE_ID,
            blueprint_id=blueprint_id,
            run_result=run_result,
            created_by=created_by,
            metadata={"source": "eval_lab_readiness_suite"},
        )

    async def persist_run_result(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        suite_id: str,
        run_result: EvalRunResult,
        blueprint_id: str | None = None,
        created_by: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReadinessEvalResult:
        score = _score_for_run(run_result)
        failed = [
            {
                "id": result.scenario_id,
                "name": result.name,
                "error": result.error,
                "failed_scorers": [
                    score.scorer for score in result.scores if not score.passed
                ],
            }
            for result in run_result.results
            if not result.passed
        ]
        policy_failures = [
            {
                "scenario_id": result.scenario_id,
                "scorer": score.scorer,
                "message": score.message,
                "metadata": score.metadata,
            }
            for result in run_result.results
            for score in result.scores
            if not score.passed
        ]
        row = AgentReadinessEvalResult(
            tenant_id=tenant_id,
            agent_id=agent_id,
            suite_id=suite_id,
            blueprint_id=blueprint_id,
            score=score,
            passed=run_result.passed,
            scenario_count=run_result.total,
            failed_scenarios=failed,
            policy_failures=policy_failures,
            created_by=created_by,
            metadata_json={
                **(metadata or {}),
                "passed_count": run_result.passed_count,
                "failed_count": run_result.failed_count,
            },
        )
        self._session.add(row)
        await self._session.flush()
        if row.passed:
            await self._mark_onboarding_test_passed(
                tenant_id=tenant_id,
                agent_id=agent_id,
                result=row,
            )
        return row

    async def record_test_turn_evidence(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        output: TurnOutput,
        policy_issues: Sequence[Any],
        requires_knowledge: bool = False,
        created_by: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentReadinessEvalResult:
        failed: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        if policy_issues:
            failures.append(
                {
                    "scorer": "policy_validator",
                    "message": "PolicyValidator returned issues.",
                    "metadata": {
                        "issues": [
                            _issue_payload(issue) for issue in policy_issues
                        ]
                    },
                }
            )
        if not output.final_message.strip():
            failures.append(
                {
                    "scorer": "did_not_emit_empty_response",
                    "message": "final_message is empty.",
                    "metadata": {},
                }
            )
        if requires_knowledge and not output.knowledge_citations:
            failures.append(
                {
                    "scorer": "required_knowledge_citations",
                    "message": "Knowledge citations are required for this test evidence.",
                    "metadata": {},
                }
            )
        passed = not failures
        if not passed:
            failed.append(
                {
                    "id": "agent_test_turn_v2",
                    "name": "Agent Test Turn v2 evidence",
                    "failed_scorers": [item["scorer"] for item in failures],
                }
            )
        row = AgentReadinessEvalResult(
            tenant_id=tenant_id,
            agent_id=agent_id,
            suite_id=TEST_TURN_SUITE_ID,
            score=1.0 if passed else 0.0,
            passed=passed,
            scenario_count=1,
            failed_scenarios=failed,
            policy_failures=failures,
            created_by=created_by,
            metadata_json={
                **(metadata or {}),
                "source": "agent_test_turn_v2",
                "requires_knowledge": requires_knowledge,
                "citation_count": len(output.knowledge_citations),
            },
        )
        self._session.add(row)
        await self._session.flush()
        if row.passed:
            await self._mark_onboarding_test_passed(
                tenant_id=tenant_id,
                agent_id=agent_id,
                result=row,
            )
        return row

    async def get_latest_readiness_result(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None = None,
        suite_id: str | None = None,
    ) -> AgentReadinessEvalResult | None:
        stmt = select(AgentReadinessEvalResult).where(
            AgentReadinessEvalResult.tenant_id == tenant_id
        )
        if agent_id is not None:
            stmt = stmt.where(AgentReadinessEvalResult.agent_id == agent_id)
        if suite_id is not None:
            stmt = stmt.where(AgentReadinessEvalResult.suite_id == suite_id)
        return (
            await self._session.execute(
                stmt.order_by(AgentReadinessEvalResult.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

    async def is_agent_ready_for_send(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None,
        min_score: float | None = None,
    ) -> bool:
        return (
            await self.explain_readiness(
                tenant_id=tenant_id,
                agent_id=agent_id,
                min_score=min_score,
            )
        ).ready

    async def explain_readiness(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None,
        min_score: float | None = None,
    ) -> ReadinessDecision:
        if agent_id is None:
            return ReadinessDecision(False, ["conversation has no assigned agent"])
        result = await self.get_latest_readiness_result(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        if result is None:
            return ReadinessDecision(False, ["readiness result is missing"])
        reasons: list[str] = []
        if not result.passed:
            reasons.append("latest readiness result did not pass")
        required = DEFAULT_MIN_READINESS_SCORE if min_score is None else min_score
        if float(result.score) < required:
            reasons.append(f"readiness score is below required minimum {required}")
        if not reasons:
            reasons.append("latest readiness result passed")
        return ReadinessDecision(
            ready=not any(reason != "latest readiness result passed" for reason in reasons),
            reasons=reasons,
            result=result,
        )

    async def _mark_onboarding_test_passed(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        result: AgentReadinessEvalResult,
    ) -> None:
        state = (
            await self._session.execute(
                select(OnboardingState).where(OnboardingState.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if state is None:
            return
        state.test_passed = True
        checklist = dict(state.checklist or {})
        checklist["test_passed"] = True
        checklist["readiness"] = readiness_result_payload(result)
        checklist["readiness_agent_id"] = str(agent_id)
        state.checklist = checklist


def readiness_result_payload(row: AgentReadinessEvalResult | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "agent_id": str(row.agent_id),
        "suite_id": row.suite_id,
        "blueprint_id": row.blueprint_id,
        "score": float(row.score),
        "passed": row.passed,
        "scenario_count": row.scenario_count,
        "failed_scenarios": row.failed_scenarios or [],
        "policy_failures": row.policy_failures or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": str(row.created_by) if row.created_by else None,
        "metadata": dict(row.metadata_json or {}),
    }


def _scenarios_for_readiness(
    *,
    tenant_id: UUID,
    agent_id: UUID,
    blueprint_id: str | None,
) -> list[EvalScenario]:
    scenarios = list(generic_scenarios())
    blueprint_keys = _BLUEPRINT_SCENARIO_MAP.get(blueprint_id or "", ())
    blueprints = blueprint_scenarios()
    for key in blueprint_keys:
        scenarios.extend(blueprints.get(key, []))
    return [
        scenario.model_copy(
            update={
                "tenant_id": str(tenant_id),
                "conversation_id": f"readiness-{agent_id}-{scenario.id}",
                "metadata": {
                    **scenario.metadata,
                    "agent_id": str(agent_id),
                    "blueprint_id": blueprint_id,
                    "readiness_gate": True,
                    "side_effects_allowed": False,
                },
            }
        )
        for scenario in scenarios
    ]


def _score_for_run(run_result: EvalRunResult) -> float:
    if run_result.total <= 0:
        return 0.0
    return round(run_result.passed_count / run_result.total, 4)


def _issue_payload(issue: Any) -> dict[str, Any]:
    if hasattr(issue, "model_dump"):
        return issue.model_dump(mode="json")
    if isinstance(issue, dict):
        return dict(issue)
    return {"message": str(issue)}

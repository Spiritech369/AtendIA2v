"""DB/API adapter for the Respond-Style direct Test Lab (no-send).

Runs Test Lab suites over the direct ProductAgentRuntime path
(config adapter -> context builder -> budgeted tool loop -> validator) and
stores evidence as an AgentTestRun row (mode='no_send'). It never sends,
never enqueues, never executes workflows/actions, and never touches the
legacy Test Lab pipeline in ``test_lab.py``.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime import (
    InMemoryEvidenceSink,
    ProductAgentPublishedConfig,
    RespondStyleLLMTurnProvider,
    RespondStyleTestLabDirect,
    RespondStyleToolLoop,
    TestLabScenario,
    TestLabScenarioResult,
    published_config_from_version_payload,
)
from atendia.agent_runtime.respond_style_dry_facts_executor import DryFactsToolExecutor
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoopConfig
from atendia.config import get_settings
from atendia.db.models.product_agent import AgentTestRun, AgentVersion
from atendia.product_agents import service

DIRECT_DECISION_READY = "RESPOND_STYLE_DIRECT_NO_SEND_READY"
DIRECT_DECISION_BLOCKED = "RESPOND_STYLE_DIRECT_NO_SEND_BLOCKED"
DIRECT_EXECUTION_MODE = "respond_style_product_agent_direct"


class ToolLoopFactory(Protocol):
    def __call__(self, config: ProductAgentPublishedConfig) -> RespondStyleToolLoop: ...


async def run_direct_test_suite(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    created_by_user_id: UUID | None,
    tool_loop_factory: ToolLoopFactory | None = None,
    max_tool_rounds: int = 3,
) -> AgentTestRun:
    suite = await service.get_agent_test_suite_for_tenant(
        session,
        tenant_id=tenant_id,
        suite_id=suite_id,
    )
    scenarios = await service.list_agent_test_scenarios(
        session,
        tenant_id=tenant_id,
        suite_id=suite_id,
    )
    version = await session.get(AgentVersion, suite.agent_version_id)
    if version is None or version.tenant_id != tenant_id:
        raise service.ProductAgentNotFoundError(
            "agent version for the suite was not found"
        )

    config = _config_from_version(version)
    factory = tool_loop_factory or _default_tool_loop_factory(max_tool_rounds)
    sink = InMemoryEvidenceSink()
    lab = RespondStyleTestLabDirect(
        config=config,
        tool_loop_factory=lambda: factory(config),
        evidence_sink=sink,
    )
    results = await lab.run_scenarios(
        [_scenario_from_record(record) for record in scenarios]
    )

    run = service.create_agent_test_run_record(
        tenant_id=tenant_id,
        agent_version_id=suite.agent_version_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=False,
        created_by_user_id=created_by_user_id,
    )
    _apply_evidence(run, results)
    session.add(run)
    await session.flush()
    return run


def _config_from_version(version: AgentVersion) -> ProductAgentPublishedConfig:
    payload: dict[str, Any] = {
        "role": version.role,
        "tone": version.tone,
        "language": version.language,
        "instructions": version.instructions,
        "knowledge_policy": dict(version.knowledge_policy or {}),
        "tool_policy": dict(version.tool_policy or {}),
        "action_policy": dict(version.action_policy or {}),
        "workflow_policy": dict(version.workflow_policy or {}),
        "field_policy": dict(version.field_policy or {}),
        "safety_policy": dict(version.safety_policy or {}),
    }
    return published_config_from_version_payload(
        payload,
        tenant_id=str(version.tenant_id),
        agent_id=str(version.agent_id),
        agent_version_id=str(version.id),
        publish_state=version.status,
    )


def _default_tool_loop_factory(max_tool_rounds: int) -> ToolLoopFactory:
    def factory(config: ProductAgentPublishedConfig) -> RespondStyleToolLoop:
        api_key = get_settings().openai_api_key
        if not api_key:
            raise service.ProductAgentError(
                "openai_api_key is not configured for direct Test Lab runs"
            )
        return RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=DryFactsToolExecutor(config.tool_bindings),
            config=RespondStyleToolLoopConfig(max_tool_rounds=max_tool_rounds),
        )

    return factory


def _scenario_from_record(record: Any) -> TestLabScenario:
    turns: list[str] = []
    for turn in record.turns or []:
        if isinstance(turn, str):
            text = turn.strip()
        elif isinstance(turn, dict):
            text = str(
                turn.get("inbound_text") or turn.get("text") or turn.get("message") or ""
            ).strip()
        else:
            text = ""
        if text:
            turns.append(text)
    if not turns:
        turns = ["hola"]
    return TestLabScenario(
        name=str(record.name),
        turns=turns,
        expected=dict(record.expected or {}),
    )


def _apply_evidence(run: AgentTestRun, results: list[TestLabScenarioResult]) -> None:
    all_turns = [turn for result in results for turn in result.turns]
    blocked = [turn for turn in all_turns if turn.blocked_reason is not None]
    run.scenario_results = [result.model_dump(mode="json") for result in results]
    run.turn_results = [turn.model_dump(mode="json") for turn in all_turns]
    run.pass_count = sum(1 for turn in all_turns if turn.simulated_outbound)
    run.fail_count = 0
    run.blocked_count = len(blocked)
    run.status = "passed" if not blocked else "blocked"
    run.decision = DIRECT_DECISION_READY if not blocked else DIRECT_DECISION_BLOCKED
    run.outbox_audit_result = {"status": "clean", "outbound_outbox_writes": 0}
    run.side_effect_audit_result = {
        "status": "clean",
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }
    run.coverage_summary = {
        "execution_mode": DIRECT_EXECUTION_MODE,
        "send_decision": "no_send",
        "outbound_outbox_writes": 0,
        "side_effects": {
            "delivery": False,
            "workflows": False,
            "actions": False,
            "field_writes": False,
        },
    }


__all__ = [
    "DIRECT_DECISION_BLOCKED",
    "DIRECT_DECISION_READY",
    "DIRECT_EXECUTION_MODE",
    "run_direct_test_suite",
]

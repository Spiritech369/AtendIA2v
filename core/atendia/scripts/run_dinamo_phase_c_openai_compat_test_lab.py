"""Run Dinamo Phase C provider-compat Test Lab without real OpenAI.

This script exercises the same RespondStyleLLMTurnProvider path used by
OpenAI-backed direct runs, but injects a deterministic local client. It stores
DB-backed Test Lab evidence as no-send, never calls external APIs, never sends,
and never writes outbox rows.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.run_dinamo_phase_c_openai_compat_test_lab \
        --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.respond_style_dry_facts_executor import DryFactsToolExecutor
from atendia.agent_runtime.respond_style_llm_provider import RespondStyleLLMTurnProvider
from atendia.agent_runtime.respond_style_tool_loop import (
    RespondStyleToolLoop,
    RespondStyleToolLoopConfig,
)
from atendia.db.models.agent import Agent
from atendia.db.models.outbound_outbox import OutboundOutbox
from atendia.db.models.product_agent import AgentDeployment, AgentTestRun, AgentVersion
from atendia.db.session import get_db_session
from atendia.product_agents import service, test_lab_direct_adapter
from atendia.product_agents.test_lab_direct_adapter import DIRECT_DECISION_READY
from atendia.scripts.seed_dinamo_phase_c_agent import PHASE_C_SEED_ID
from atendia.scripts.seed_dinamo_v1 import AGENT_NAME, SEED_ID

JsonDict = dict[str, Any]

SOURCE = "dinamo_phase_c_openai_compat_test_lab"
COMPAT_EXECUTION_MODE = "openai_direct_provider_fake_client"
COMPAT_PROVIDER_CLASS = "RespondStyleLLMTurnProvider"
COMPAT_DECISION_READY = "RESPOND_STYLE_OPENAI_COMPAT_NO_SEND_READY"
COMPAT_DECISION_BLOCKED = "RESPOND_STYLE_OPENAI_COMPAT_NO_SEND_BLOCKED"


@dataclass(frozen=True)
class CompatScenario:
    key: str
    name: str
    turns: tuple[str, ...]
    expected_tools: tuple[str, ...] = ()
    final_message_contains: tuple[str, ...] = ()
    forbidden_final_message_contains: tuple[str, ...] = (
        "/goal",
        "trace",
        "prompt",
        "workflow",
        "outbox",
        "StateWriter",
        "te paso con Francisco",
        "te paso con Frank",
    )

    def as_expected(self) -> JsonDict:
        return {
            "expected_tools": list(self.expected_tools),
            "final_message_contains": list(self.final_message_contains),
            "forbidden_final_message_contains": list(
                self.forbidden_final_message_contains
            ),
            "openai_api_real": False,
            "send": "no_send",
        }


@dataclass
class PhaseCOpenAICompatResult:
    tenant_id: str
    suite_id: str
    run_id: str
    status: str
    decision: str
    pass_count: int
    blocked_count: int
    outbox_before: int
    outbox_after: int
    outbox_delta: int
    deployments_no_send: bool
    provider_class: str = COMPAT_PROVIDER_CLASS
    execution_mode: str = COMPAT_EXECUTION_MODE
    assertions: list[str] = field(default_factory=list)

    def as_dict(self) -> JsonDict:
        return {
            "tenant_id": self.tenant_id,
            "suite_id": self.suite_id,
            "run_id": self.run_id,
            "status": self.status,
            "decision": self.decision,
            "pass_count": self.pass_count,
            "blocked_count": self.blocked_count,
            "outbox_before": self.outbox_before,
            "outbox_after": self.outbox_after,
            "outbox_delta": self.outbox_delta,
            "deployments_no_send": self.deployments_no_send,
            "provider_class": self.provider_class,
            "execution_mode": self.execution_mode,
            "assertions": self.assertions,
            "openai_api_real": False,
            "external_apis": False,
            "send": "no_send",
        }


def compat_scenarios() -> tuple[CompatScenario, ...]:
    return (
        CompatScenario(
            key="phase_c_identity_greeting",
            name="Phase C OpenAI provider compat greeting",
            turns=("Hola, quiero info de credito",),
            final_message_contains=("cuanto tiempo llevas trabajando",),
        ),
        CompatScenario(
            key="phase_c_quote_tool_request",
            name="Phase C OpenAI provider compat quote tool",
            turns=("Cotiza Adventure Elite con nomina en tarjeta",),
            expected_tools=("quote.resolve",),
            final_message_contains=("cotizacion validada",),
        ),
    )


async def run_phase_c_openai_compat_test_lab(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    created_by_user_id: UUID | None = None,
) -> PhaseCOpenAICompatResult:
    outbox_before = await _outbox_count(session, tenant_id)
    deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_phase_c_dinamo_version(session, tenant_id)
    _assert_phase_c_version(version)

    scenarios = compat_scenarios()
    suite = await _create_suite(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
        scenarios=scenarios,
    )
    run = await test_lab_direct_adapter.run_direct_test_suite(
        session,
        tenant_id=tenant_id,
        suite_id=suite.id,
        created_by_user_id=created_by_user_id,
        tool_loop_factory=_tool_loop_factory,
        max_tool_rounds=3,
    )
    assertions = _assert_run_contract(run, scenarios)
    _annotate_suite_and_run(suite, run, scenarios)

    if run.decision != COMPAT_DECISION_READY:
        raise service.ProductAgentError("Phase C provider compat Test Lab did not pass")

    outbox_after = await _outbox_count(session, tenant_id)
    if outbox_after != outbox_before:
        raise service.ProductAgentError("outbox changed during no-send compat run")

    return PhaseCOpenAICompatResult(
        tenant_id=str(tenant_id),
        suite_id=str(suite.id),
        run_id=str(run.id),
        status=run.status,
        decision=run.decision,
        pass_count=run.pass_count,
        blocked_count=run.blocked_count,
        outbox_before=outbox_before,
        outbox_after=outbox_after,
        outbox_delta=outbox_after - outbox_before,
        deployments_no_send=deployments_no_send,
        assertions=assertions,
    )


async def _load_phase_c_dinamo_version(
    session: AsyncSession,
    tenant_id: UUID,
) -> tuple[Agent, AgentVersion]:
    agent = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == AGENT_NAME)
        )
    ).scalars().one_or_none()
    if agent is None:
        raise service.ProductAgentNotFoundError("Dinamo seeded agent was not found")
    version = (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.version_number.desc())
        )
    ).scalars().first()
    if version is None:
        raise service.ProductAgentNotFoundError("Dinamo seeded agent version was not found")
    return agent, version


def _assert_phase_c_version(version: AgentVersion) -> None:
    snapshot = dict(version.snapshot or {})
    if snapshot.get("phase") != "C":
        raise service.ProductAgentError("latest Dinamo version is not Phase C")
    policy = dict(version.tool_policy or {})
    bindings = policy.get("bindings") or []
    tool_names = {
        str(binding.get("name") or binding.get("tool_name"))
        for binding in bindings
        if isinstance(binding, dict)
    }
    missing = {"catalog.search", "quote.resolve", "requirements.lookup"} - tool_names
    if missing:
        raise service.ProductAgentError(
            "Phase C required tool bindings are missing: " + ", ".join(sorted(missing))
        )
    prompt_block_ids = {
        str(block.get("id"))
        for block in version.prompt_blocks or []
        if isinstance(block, dict)
    }
    if "dinamo_phase_c_runtime_authority_v1" not in prompt_block_ids:
        raise service.ProductAgentError("Phase C runtime authority prompt is missing")


async def _create_suite(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
    scenarios: tuple[CompatScenario, ...],
):
    timestamp = datetime.now(UTC).isoformat()
    suite = await service.create_agent_test_suite(
        session,
        tenant_id=tenant_id,
        version_id=version_id,
        name=f"Dinamo V1 Phase C OpenAI provider compat no-send - {timestamp}",
        mode="publish_readiness",
        metadata={
            "source": SOURCE,
            "seed_id": SEED_ID,
            "phase_seed_id": PHASE_C_SEED_ID,
            "provider_class": COMPAT_PROVIDER_CLASS,
            "execution_mode": COMPAT_EXECUTION_MODE,
            "fake_openai_client": True,
            "openai_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "scenario_keys": [scenario.key for scenario in scenarios],
        },
    )
    for scenario in scenarios:
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.name,
            turns=[{"inbound_text": turn} for turn in scenario.turns],
            expected=scenario.as_expected(),
            metadata={
                "scenario_key": scenario.key,
                "source": SOURCE,
                "provider_class": COMPAT_PROVIDER_CLASS,
                "execution_mode": COMPAT_EXECUTION_MODE,
                "fake_openai_client": True,
                "openai_api_real": False,
                "external_apis": False,
            },
        )
    return suite


def _tool_loop_factory(config) -> RespondStyleToolLoop:
    return RespondStyleToolLoop(
        provider=RespondStyleLLMTurnProvider(client=_FakeOpenAIClient()),
        executor=DryFactsToolExecutor(config.tool_bindings),
        config=RespondStyleToolLoopConfig(max_tool_rounds=3, max_total_tool_calls=8),
    )


class _FakeOpenAIClient:
    """OpenAI-compatible local client used only for no-send compatibility tests."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions())


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[JsonDict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        messages = kwargs.get("messages") or []
        output = _fake_llm_output(messages)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=40),
        )


def _fake_llm_output(messages: list[JsonDict]) -> str:
    content = "\n".join(str(message.get("content") or "") for message in messages)
    folded = content.casefold()
    if "cotiza adventure elite" in folded and "quote.resolve" not in _tool_result_text(folded):
        return _json_output(
            turn_kind="tool_request",
            final_message=None,
            tool_requests=[
                {
                    "tool_name": "quote.resolve",
                    "arguments": _tool_arguments(
                        Moto="Adventure Elite 150 CC",
                        Plan_Credito="Nomina tarjeta",
                    ),
                    "reason": "Need tenant-approved quote facts before answering.",
                    "required": True,
                }
            ],
        )
    if "cotiza adventure elite" in folded:
        return _json_output(
            final_message=(
                "Ya tengo la cotizacion validada para Adventure Elite 150 CC "
                "con plan nomina tarjeta."
            ),
            claims=[
                {
                    "text": "La cotizacion fue validada con la fuente de quote.",
                    "basis": "tool_result",
                    "source_refs": ["tool:quote.resolve"],
                }
            ],
        )
    return _json_output(
        final_message=(
            "Claro, para ayudarte bien dime cuanto tiempo llevas trabajando."
        ),
        claims=[
            {
                "text": "El siguiente paso es pedir antiguedad laboral.",
                "basis": "agent_policy",
                "source_refs": [],
            }
        ],
    )


def _tool_result_text(folded_content: str) -> str:
    marker = "## tool results from this turn"
    index = folded_content.rfind(marker)
    if index < 0:
        return ""
    return folded_content[index:]


def _json_output(**overrides) -> str:
    payload = {
        "turn_kind": "final_response",
        "final_message": "Listo.",
        "tool_requests": [],
        "field_write_proposals": [],
        "action_proposals": [],
        "workflow_event_proposals": [],
        "handoff_proposal": None,
        "claims": [],
        "confidence": 0.85,
        "needs_retry_reason": None,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _tool_arguments(**values: str) -> JsonDict:
    return {
        "summary": "Tenant fact lookup arguments.",
        "values": [
            {"key": key, "string_value": value}
            for key, value in values.items()
        ],
    }


def _assert_run_contract(
    run: AgentTestRun,
    scenarios: tuple[CompatScenario, ...],
) -> list[str]:
    failures: list[str] = []
    turn_results = list(run.turn_results or [])
    if len(turn_results) != len(scenarios):
        failures.append("turn_result_count_mismatch")
    for scenario, turn in zip(scenarios, turn_results, strict=False):
        failures.extend(_assert_turn_contract(scenario, turn))
    if run.status != "passed" or run.decision != DIRECT_DECISION_READY:
        failures.append("direct_provider_run_not_ready")
    if failures:
        run.status = "failed"
        run.decision = COMPAT_DECISION_BLOCKED
        run.fail_count = len(failures)
        run.coverage_summary = {
            **(run.coverage_summary or {}),
            "assertion_failures": failures,
            "openai_api_real": False,
            "external_apis": False,
        }
        raise service.ProductAgentError(
            "Dinamo Phase C provider compat assertions failed: "
            + ", ".join(failures)
        )
    return ["passed"]


def _assert_turn_contract(scenario: CompatScenario, turn: JsonDict) -> list[str]:
    failures: list[str] = []
    if turn.get("blocked_reason") is not None:
        failures.append(f"{scenario.key}:unexpected_blocked:{turn.get('blocked_reason')}")
    tools = {
        item.get("tool_name")
        for item in turn.get("tools") or []
        if item.get("status") == "succeeded"
    }
    for tool in scenario.expected_tools:
        if tool not in tools:
            failures.append(f"{scenario.key}:missing_tool:{tool}")
    final_message = str(turn.get("final_message") or "")
    for expected in scenario.final_message_contains:
        if expected.casefold() not in final_message.casefold():
            failures.append(f"{scenario.key}:final_message_missing:{expected}")
    for forbidden in scenario.forbidden_final_message_contains:
        if forbidden.casefold() in final_message.casefold():
            failures.append(f"{scenario.key}:final_message_forbidden:{forbidden}")
    return failures


def _annotate_suite_and_run(
    suite,
    run: AgentTestRun,
    scenarios: tuple[CompatScenario, ...],
) -> None:
    suite.last_run_id = run.id
    suite.status = "passed" if run.decision == DIRECT_DECISION_READY else "blocked"
    run.decision = (
        COMPAT_DECISION_READY if run.decision == DIRECT_DECISION_READY else COMPAT_DECISION_BLOCKED
    )
    run.coverage_summary = {
        **(run.coverage_summary or {}),
        "source": SOURCE,
        "scenario_keys": [scenario.key for scenario in scenarios],
        "provider_class": COMPAT_PROVIDER_CLASS,
        "execution_mode": COMPAT_EXECUTION_MODE,
        "fake_openai_client": True,
        "openai_api_real": False,
        "external_apis": False,
        "send_decision": "no_send",
        "outbound_outbox_writes": 0,
        "assertions": "passed",
    }


async def _outbox_count(session: AsyncSession, tenant_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(OutboundOutbox)
        .where(OutboundOutbox.tenant_id == tenant_id)
    )
    return int(count or 0)


async def _deployments_are_no_send(session: AsyncSession, tenant_id: UUID) -> bool:
    deployments = (
        await session.execute(
            select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
        )
    ).scalars().all()
    return bool(deployments) and all(
        not deployment.send_enabled
        and not deployment.outbox_enabled
        and not deployment.live_send_enabled
        and not deployment.single_contact_smoke_enabled
        and not deployment.actions_enabled
        and not deployment.workflow_events_enabled
        and not deployment.workflow_side_effects_enabled
        and not deployment.canary_enabled
        and not deployment.open_production_enabled
        and deployment.send_scope == "none"
        and deployment.runtime_mode == "no_send"
        for deployment in deployments
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Dinamo Phase C OpenAI-provider compatibility Test Lab."
    )
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--created-by-user-id", type=UUID, default=None)
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    async for session in get_db_session():
        try:
            result = await run_phase_c_openai_compat_test_lab(
                session,
                tenant_id=args.tenant_id,
                created_by_user_id=args.created_by_user_id,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPAT_DECISION_BLOCKED",
    "COMPAT_DECISION_READY",
    "COMPAT_EXECUTION_MODE",
    "COMPAT_PROVIDER_CLASS",
    "PhaseCOpenAICompatResult",
    "_FakeOpenAIClient",
    "_assert_turn_contract",
    "compat_scenarios",
    "run_phase_c_openai_compat_test_lab",
]

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import (  # noqa: E402
    AgentContextPackage,
    AgentTurnInput,
    FinalTurnDecision,
    LLMToolCallProposal,
    RespondStyleLLMTurnProvider,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult  # noqa: E402


class _RecordingProvider:
    """Wraps the real provider and records every LLM turn for evidence."""

    def __init__(self, inner: RespondStyleLLMTurnProvider) -> None:
        self._inner = inner
        self.turns: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        decision = await self._inner.generate(turn_input=turn_input, context=context)
        raw = self._inner.last_raw_output
        turn_kind = None
        raw_final_message = None
        raw_tool_requests: list[str] = []
        if raw:
            try:
                parsed = json.loads(raw)
                turn_kind = parsed.get("turn_kind")
                raw_final_message = parsed.get("final_message")
                raw_tool_requests = [
                    item.get("tool_name")
                    for item in parsed.get("tool_requests") or []
                    if isinstance(item, dict)
                ]
            except (ValueError, TypeError):
                pass
        self.turns.append(
            {
                "turn_kind": turn_kind,
                "raw_final_message": raw_final_message,
                "raw_tool_requests": raw_tool_requests,
                "validation_status": (
                    decision.validation.status if decision.validation else None
                ),
                "decision_final_message": decision.final_message,
                "send_decision": decision.send_decision,
                "context_tool_results": [
                    item.get("tool_name")
                    for item in context.tool_results
                    if isinstance(item, dict)
                ],
            }
        )
        return decision


class _DryFactToolExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        self.calls.append(tool_call.tool_name)
        contact_state = context.agent_identity.get("contact_state") or {}
        selected_option = contact_state.get("selected_option")
        if tool_call.tool_name == "requirements.lookup":
            if not selected_option:
                return _skipped(tool_call, "missing_selected_option")
            return ToolExecutionResult(
                tool_name=tool_call.tool_name,
                status="succeeded",
                facts={
                    "selected_option": selected_option,
                    "requirements": [
                        "valid identification",
                        "proof of address",
                        "recent proof of income when applicable",
                    ],
                },
                citations=["generic-requirements-source"],
                source_refs=["requirements.lookup"],
                is_required=tool_call.required,
                can_support_claims=True,
            )
        if tool_call.tool_name == "quote.resolve":
            if not selected_option:
                return _skipped(tool_call, "missing_selected_option")
            return ToolExecutionResult(
                tool_name=tool_call.tool_name,
                status="succeeded",
                facts={"selected_option": selected_option, "price": 120, "currency": "USD"},
                citations=["generic-quote-source"],
                source_refs=["quote.resolve"],
                is_required=tool_call.required,
                can_support_claims=True,
            )
        return _skipped(tool_call, "tool_not_available")


def _skipped(tool_call: LLMToolCallProposal, error_code: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_call.tool_name,
        status="skipped",
        facts={},
        citations=[],
        source_refs=[],
        error_code=error_code,
        is_required=tool_call.required,
        can_support_claims=False,
    )


def _turn_input(text: str, *, conversation_id: str, state: dict[str, Any]) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="generic-tenant",
        deployment_id="generic-deployment",
        agent_id="generic-agent",
        agent_version_id="generic-version",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="manual_phase_0_5_no_send",
        conversation_id=conversation_id,
        contact_id="generic-contact",
        inbound_text=text,
        contact_snapshot=state,
        recent_messages=[],
    )


def _context(state: dict[str, Any]) -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={
            "name": "Generic AtendIA assistant",
            "role": "customer advisor",
            "contact_state": state,
        },
        instructions=(
            "Use configured capabilities for exact sourced facts. Ask for missing "
            "preconditions naturally. Keep customer-facing text short and human."
        ),
        voice_guide={"tone": "brief, human, clear"},
        retrieved_context=[
            {
                "source_id": "generic-info",
                "title": "General information",
                "snippet": "The team can verify exact requirements, quotes, and alternatives.",
            }
        ],
        tool_schemas=[
            {
                "name": "requirements.lookup",
                "tool_name": "requirements.lookup",
                "enabled": True,
                "capability": "resolve exact requirements when selected_option exists",
                "preconditions": ["selected_option"],
                "when_to_use": [
                    "contact_state.requested_fact is requirements",
                    "customer asks what is needed for a selected option",
                    "customer names a selected option and wants to proceed",
                ],
                "returns": ["requirements", "source_refs"],
            },
            {
                "name": "quote.resolve",
                "tool_name": "quote.resolve",
                "enabled": True,
                "capability": "resolve exact quote when selected_option exists",
                "preconditions": ["selected_option"],
                "when_to_use": [
                    "contact_state.requested_fact is quote",
                    "customer asks exact cost for a selected option",
                ],
                "returns": ["price", "currency", "source_refs"],
            },
        ],
        field_policies=[
            {"field_key": "lead_intent", "writable": True},
            {"field_key": "work_type", "writable": True},
        ],
        workflow_trigger_schemas=[],
        action_schemas=[],
        handoff_policy={"enabled": True, "targets": ["sales", "support"]},
    )


def _api_key_from_env() -> tuple[str | None, str | None]:
    for env_name in ("OPENAI_API_KEY", "ATENDIA_V2_OPENAI_API_KEY"):
        value = os.getenv(env_name)
        if value:
            return value, env_name
    for path in (REPO_ROOT / ".env", CORE_ROOT / ".env"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in ("OPENAI_API_KEY", "ATENDIA_V2_OPENAI_API_KEY"):
                cleaned = value.strip().strip("'\"")
                if cleaned:
                    return cleaned, f"{path.name}:{key.strip()}"
    return None, None


def _scenario_checks(
    *,
    provider: _RecordingProvider,
    executor: _DryFactToolExecutor,
    decision: FinalTurnDecision,
) -> dict[str, Any]:
    turns = provider.turns
    first = turns[0] if turns else {}
    last = turns[-1] if turns else {}
    tool_round_ran = len(turns) >= 2 and bool(executor.calls)
    return {
        "turn1_kind": first.get("turn_kind"),
        "turn1_is_tool_request": first.get("turn_kind") == "tool_request",
        "turn1_has_no_visible_message": not (first.get("raw_final_message") or "").strip(),
        "turn1_tool_requests": first.get("raw_tool_requests"),
        "tool_executed": list(executor.calls),
        "tool_result_returned_to_turn2": bool(last.get("context_tool_results"))
        if tool_round_ran
        else False,
        "turn2_kind": last.get("turn_kind") if tool_round_ran else None,
        "turn2_is_final_response": (
            last.get("turn_kind") == "final_response" if tool_round_ran else False
        ),
        "final_validation_status": (
            decision.validation.status if decision.validation else None
        ),
        "final_message": decision.final_message,
        "send_decision": decision.send_decision,
        "llm_turns_total": len(turns),
    }


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "PHASE_0_5_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                    "side_effects": {"outbox": False, "workflows": False, "actions": False},
                },
                indent=2,
            )
        )
        return 0

    scenarios = [
        # The Phase 6 fail-closed scenario: customer names an option;
        # requirements/quote facts require tools that have not run yet.
        (
            "model",
            "metro",
            {"selected_option": "metro", "requested_fact": "requirements"},
        ),
        (
            "requirements_generic",
            "que ocupo",
            {"selected_option": "standard option", "requested_fact": "requirements"},
        ),
        (
            "price_direct",
            "cuanto cuesta",
            {"selected_option": "standard option", "requested_fact": "quote"},
        ),
    ]

    results: list[dict[str, Any]] = []
    for index, (name, text, state) in enumerate(scenarios, start=1):
        provider = _RecordingProvider(RespondStyleLLMTurnProvider(api_key=api_key))
        executor = _DryFactToolExecutor()
        loop = RespondStyleToolLoop(provider=provider, executor=executor)
        decision = await loop.run(
            turn_input=_turn_input(text, conversation_id=f"phase05-{index}", state=state),
            context=_context(state),
        )
        checks = _scenario_checks(provider=provider, executor=executor, decision=decision)
        checks["scenario"] = name
        checks["inbound_text"] = text
        results.append(checks)

    model_result = next(item for item in results if item["scenario"] == "model")
    amended_flow_verified = (
        model_result["turn1_is_tool_request"]
        and model_result["turn1_has_no_visible_message"]
        and bool(model_result["tool_executed"])
        and model_result["tool_result_returned_to_turn2"]
        and model_result["turn2_is_final_response"]
        and model_result["final_validation_status"] == "valid"
        and model_result["send_decision"] == "no_send"
        and bool(model_result["final_message"])
    )
    all_no_send = all(item["send_decision"] == "no_send" for item in results)

    print(
        json.dumps(
            {
                "decision": (
                    "RESPOND_STYLE_CONTRACT_VALIDATOR_AMENDED_VERIFIED_NO_SEND"
                    if amended_flow_verified and all_no_send
                    else "PHASE_0_5_BLOCKED_BY_MODEL_BEHAVIOR"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "model_scenario_amended_flow_verified": amended_flow_verified,
                "all_scenarios_no_send": all_no_send,
                "results": results,
                "side_effects": {
                    "outbox": False,
                    "workflows": False,
                    "actions": False,
                    "delivery": False,
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

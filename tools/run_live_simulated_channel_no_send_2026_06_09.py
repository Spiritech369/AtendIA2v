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
    LiveSimulatedChannel,
    LLMToolCallProposal,
    ProductAgentPublishedConfig,
    RespondStyleLLMTurnProvider,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult  # noqa: E402


def _generic_config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v1",
        deployment_id="live-simulated-no-send",
        publish_state="published",
        agent_name="Generic Assistant",
        persona="warm, direct human advisor for a generic product line",
        instructions=(
            "Help the customer choose and move forward using configured "
            "capabilities for exact sourced facts. Ask for missing details "
            "naturally, one at a time. Keep messages short and human."
        ),
        language="es",
        tone="brief, warm, human",
        kb_snippets=[
            {
                "source_id": "kb-general-overview",
                "title": "General overview",
                "excerpt": (
                    "The team offers a standard option and a premium option. "
                    "Exact quotes and requirement lists come from the internal "
                    "verification system. A human teammate is available on request."
                ),
            }
        ],
        tool_bindings=[
            {
                "name": "catalog.search",
                "description": "Finds catalog options matching structured filters.",
            },
            {
                "name": "quote.resolve",
                "description": "Returns an exact quote for a validated selected option.",
                "preconditions": ["selected_option"],
            },
            {
                "name": "requirements.lookup",
                "description": (
                    "Returns the factual requirement list for a validated selected option."
                ),
                "preconditions": ["selected_option"],
            },
        ],
        field_definitions=[
            {"field_key": "selected_option", "required": True},
            {"field_key": "work_type", "required": False},
            {"field_key": "budget_concern", "required": False},
        ],
        workflow_bindings=[
            {
                "binding_name": "ready_for_handoff",
                "event_name": "lead.ready_for_handoff",
                "required_fields": ["selected_option"],
            }
        ],
        handoff={"enabled": True, "targets": ["sales", "support"]},
        hard_policies=[
            {
                "policy_id": "price_claim_requires_support",
                "trigger_patterns": [
                    r"\$\s*\d",
                    r"\b\d[\d,.]*\s*(?:mil\s+)?(?:mxn|pesos?|usd)\b",
                ],
                "requires_any": ["tool:quote.resolve", "basis:knowledge_source"],
            },
            {
                "policy_id": "requirements_claim_requires_support",
                "trigger_patterns": [r"\b(?:requisitos?|requirements?)\b"],
                "requires_any": ["tool:requirements.lookup", "basis:knowledge_source"],
            },
        ],
    )


class _DryFactToolExecutor:
    """Fact-only executor. Resolves selected_option from simulated contact
    state or from the structured tool arguments."""

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        selected_option = self._selected_option(tool_call, context)
        if tool_call.tool_name == "catalog.search":
            return self._ok(
                tool_call,
                {"options": ["standard option", "premium option"]},
            )
        if tool_call.tool_name == "quote.resolve":
            if not selected_option:
                return self._skip(tool_call, "missing_selected_option")
            return self._ok(
                tool_call,
                {
                    "selected_option": selected_option,
                    "price": 120,
                    "currency": "USD",
                    "billing": "monthly",
                },
            )
        if tool_call.tool_name == "requirements.lookup":
            if not selected_option:
                return self._skip(tool_call, "missing_selected_option")
            return self._ok(
                tool_call,
                {
                    "selected_option": selected_option,
                    "requirements": [
                        "valid identification",
                        "proof of address",
                        "recent proof of income when applicable",
                    ],
                },
            )
        return self._skip(tool_call, "tool_not_available")

    @staticmethod
    def _selected_option(
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> str | None:
        contact_state = context.agent_identity.get("contact_state") or {}
        value = contact_state.get("selected_option")
        if value:
            return str(value)
        arguments = tool_call.arguments or {}
        for item in arguments.get("values") or []:
            if isinstance(item, dict) and item.get("key") == "selected_option":
                if item.get("string_value"):
                    return str(item["string_value"])
        return None

    @staticmethod
    def _ok(tool_call: LLMToolCallProposal, facts: dict[str, Any]) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="succeeded",
            facts=facts,
            citations=[f"{tool_call.tool_name}-source"],
            source_refs=[tool_call.tool_name],
            is_required=tool_call.required,
            can_support_claims=True,
        )

    @staticmethod
    def _skip(tool_call: LLMToolCallProposal, error_code: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="skipped",
            error_code=error_code,
            is_required=tool_call.required,
            can_support_claims=False,
        )


SCENARIOS: list[dict[str, Any]] = [
    {"name": "greeting_info", "turns": ["hola", "busco informacion de sus opciones"]},
    {
        "name": "requirements",
        "turns": ["me interesa la opcion estandar", "que necesito para avanzar?"],
    },
    {"name": "price", "turns": ["cuanto cuesta la opcion estandar?"]},
    {
        "name": "ambiguous_merchant",
        "turns": ["tengo un negocio propio, no se si aplico para esto"],
    },
    {
        "name": "price_objection",
        "turns": ["me interesa la opcion estandar", "esta muy caro, no se"],
    },
    {
        "name": "robot_handoff",
        "turns": ["eres un robot? quiero hablar con una persona real"],
    },
    {
        "name": "chaotic",
        "turns": [
            "quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta"
        ],
    },
]


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


async def _run_scenario(name: str, turns: list[str], api_key: str) -> dict[str, Any]:
    channel = LiveSimulatedChannel(
        config=_generic_config(),
        tool_loop=RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=_DryFactToolExecutor(),
        ),
        conversation_id=f"sim-{name}",
    )
    turn_summaries: list[dict[str, Any]] = []
    for text in turns:
        record = await channel.receive(text)
        turn_summaries.append(
            {
                "turn": record.turn_number,
                "inbound": record.inbound_text,
                "simulated_outbound": record.simulated_outbound,
                "final_message_candidate": record.final_message_candidate,
                "send_decision": record.send_decision,
                "blocked_reason": record.blocked_reason,
                "validation_status": record.validation_result.get("status"),
                "tools": [
                    {"tool_name": item.get("tool_name"), "status": item.get("status")}
                    for item in record.tool_results
                ],
                "field_update_proposals": record.field_update_proposals,
                "simulated_field_writes": record.simulated_field_writes,
                "workflow_event_proposals": record.workflow_event_proposals,
                "handoff_proposal": record.handoff_proposal,
                "send_policy": record.send_policy,
            }
        )
    summary = channel.summary()
    return {
        "scenario": name,
        "turns": turn_summaries,
        "transcript": channel.transcript,
        "final_contact_state": channel.field_values,
        "summary": summary.model_dump(mode="json"),
    }


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "PHASE_9_5_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                },
                indent=2,
            )
        )
        return 0

    results = []
    for scenario in SCENARIOS:
        results.append(
            await _run_scenario(scenario["name"], scenario["turns"], api_key)
        )

    all_turns = [turn for item in results for turn in item["turns"]]
    all_no_send = all(turn["send_decision"] == "no_send" for turn in all_turns)
    outbox_zero = all(
        item["summary"]["outbound_outbox_writes"] == 0 for item in results
    )
    no_side_effects = all(
        not any(item["summary"]["side_effects"].values()) for item in results
    )
    answered_turns = sum(1 for turn in all_turns if turn["simulated_outbound"])
    blocked_turns = [
        {
            "scenario": item["scenario"],
            "turn": turn["turn"],
            "blocked_reason": turn["blocked_reason"],
        }
        for item in results
        for turn in item["turns"]
        if turn["blocked_reason"]
    ]

    ready = all_no_send and outbox_zero and no_side_effects and answered_turns > 0
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_9_5_LIVE_SIMULATED_CHANNEL_ANALYSIS_READY"
                    if ready
                    else "PHASE_9_5_BLOCKED_BY_CHANNEL_BEHAVIOR"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "totals": {
                    "scenarios": len(results),
                    "turns": len(all_turns),
                    "simulated_outbound": answered_turns,
                    "blocked_turns": blocked_turns,
                    "outbound_outbox_writes": 0,
                },
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

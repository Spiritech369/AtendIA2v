"""Phase 13C — Replay of the failed V2/V3 smoke transcripts via the direct route.

The two real-world failures being replayed (generic-equivalent config):
- V2 incident: customer answered a qualifying question and then got SILENCE
  (required tool skipped because a tenant source file was missing).
- V3 incident: internal StateWriter reasoning leaked into customer copy
  ("campo no está visible").

Acceptance here: every turn either produces a validated outbound candidate
or fails closed with a structured reason — never silent tool-misconfig
silence, and NEVER an internal leak in any visible message. All no-send.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import (  # noqa: E402
    DryFactsToolExecutor,
    LiveSimulatedChannel,
    ProductAgentPublishedConfig,
    RespondStyleLLMTurnProvider,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import (  # noqa: E402
    RespondStyleToolLoopConfig,
)

sys.path.insert(0, str(REPO_ROOT / "tools"))
from run_live_simulated_channel_no_send_2026_06_09 import _api_key_from_env  # noqa: E402

INTERNAL_LEAK_MARKERS = [
    "campo no está visible",
    "campo no esta visible",
    "field_not_visible",
    "statewriter",
    "state writer",
    "no puedo registrar",
    "error técnico",
    "error tecnico",
]


def _config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v1",
        publish_state="published",
        agent_name="Generic Assistant",
        persona="warm, direct human advisor for a financed product line",
        instructions=(
            "Qualify the customer naturally (work seniority first, then income "
            "type), then help them pick an option using configured capabilities "
            "for exact sourced facts. Short, human messages."
        ),
        language="es",
        tone="brief, warm, human",
        kb_snippets=[
            {
                "source_id": "kb-overview",
                "title": "Overview",
                "excerpt": (
                    "Options are financed; eligibility depends on work seniority "
                    "and income type. Exact plans and requirement lists come from "
                    "the verification system."
                ),
            }
        ],
        tool_bindings=[
            {
                "name": "eligibility_plan.resolve",
                "description": (
                    "Resolves the correct plan for a validated income type. Use when "
                    "income_type is known."
                ),
                "preconditions": ["income_type"],
                "dry_facts": {
                    "plan": "standard plan",
                    "down_payment_percent": 30,
                },
            },
            {
                "name": "requirements.lookup",
                "description": (
                    "Returns the factual requirement list for a resolved plan."
                ),
                "preconditions": ["income_type"],
                "dry_facts": {
                    "requirements": [
                        "valid identification",
                        "proof of address",
                        "recent income proof when applicable",
                    ]
                },
            },
            {
                "name": "catalog.search",
                "description": "Finds available options and their option_id values.",
                "dry_facts": {
                    "options": [
                        {"option_id": "opt-1", "label": "standard option"},
                    ]
                },
            },
        ],
        field_definitions=[
            {"field_key": "employment_seniority", "required": True},
            {"field_key": "income_type", "required": True},
            {"field_key": "selected_option", "required": False},
        ],
        handoff={"enabled": True, "targets": ["sales", "support"]},
        hard_policies=[
            {
                "policy_id": "requirements_claim_requires_support",
                "trigger_patterns": [r"\b(?:requisitos?|requirements?)\b"],
                "requires_any": ["tool:requirements.lookup", "basis:knowledge_source"],
            },
            {
                "policy_id": "plan_claim_requires_support",
                "trigger_patterns": [r"\bplan\b[^.?!]*\d", r"\benganche\b"],
                "requires_any": [
                    "tool:eligibility_plan.resolve",
                    "basis:knowledge_source",
                ],
            },
        ],
    )


REPLAYS = [
    {
        "name": "v2_incident_replay",
        "historical_failure": "silence after qualifying answer (required tool skipped)",
        "turns": ["Hola", "Info porfavor", "Me pagan por transferencia", "?"],
    },
    {
        "name": "v3_incident_replay",
        "historical_failure": "internal leak: 'campo no está visible' on seniority answer",
        "turns": [
            "hola",
            "info porfavor",
            "15 meses",
            "me pagan por transferencia",
            "?",
        ],
    },
]


async def _replay(name: str, turns: list[str], api_key: str) -> dict:
    config = _config()
    channel = LiveSimulatedChannel(
        config=config,
        tool_loop=RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=DryFactsToolExecutor(config.tool_bindings),
            config=RespondStyleToolLoopConfig(max_tool_rounds=3),
        ),
        conversation_id=f"replay-{name}",
    )
    turn_summaries = []
    for text in turns:
        record = await channel.receive(text)
        message = (record.final_message_candidate or "").casefold()
        turn_summaries.append(
            {
                "inbound": text,
                "outbound": record.final_message_candidate,
                "send_decision": record.send_decision,
                "blocked_reason": record.blocked_reason,
                "answered": record.simulated_outbound,
                "internal_leak": any(
                    marker in message for marker in INTERNAL_LEAK_MARKERS
                ),
                "tools": [
                    {"tool_name": item.get("tool_name"), "status": item.get("status")}
                    for item in record.tool_results
                ],
                "field_writes": record.simulated_field_writes,
            }
        )
    return {
        "replay": name,
        "turns": turn_summaries,
        "transcript": channel.transcript,
        "final_contact_state": channel.field_values,
        "summary": channel.summary().model_dump(mode="json"),
    }


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(json.dumps({"decision": "PHASE_13C_BLOCKED_BY_OPENAI"}, indent=2))
        return 0

    results = [
        await _replay(item["name"], item["turns"], api_key) for item in REPLAYS
    ]
    all_turns = [turn for item in results for turn in item["turns"]]

    no_internal_leaks = not any(turn["internal_leak"] for turn in all_turns)
    all_no_send = all(turn["send_decision"] == "no_send" for turn in all_turns)
    # Historical failure modes must not reproduce:
    # every turn is either answered or carries a structured blocked reason.
    no_silent_turns = all(
        turn["answered"] or turn["blocked_reason"] for turn in all_turns
    )
    answered = sum(1 for turn in all_turns if turn["answered"])

    ready = no_internal_leaks and all_no_send and no_silent_turns and answered > 0
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_13C_FAILED_TRANSCRIPT_REPLAY_PASSED"
                    if ready
                    else "PHASE_13C_REPLAY_BLOCKED"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "totals": {
                    "turns": len(all_turns),
                    "answered": answered,
                    "internal_leaks": 0 if no_internal_leaks else "FOUND",
                },
                "historical_failures": {
                    item["name"]: item["historical_failure"] for item in REPLAYS
                },
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

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
    DeploymentView,
    DryFactsToolExecutor,
    InMemoryEvidenceSink,
    ProductAgentPublishedConfig,
    RespondStyleDeploymentResolver,
    RespondStyleLLMTurnProvider,
    RespondStyleTestLabDirect,
    RespondStyleToolLoop,
    TestLabScenario,
)
from atendia.agent_runtime.respond_style_tool_loop import (  # noqa: E402
    RespondStyleToolLoopConfig,
)

sys.path.insert(0, str(REPO_ROOT / "tools"))
from run_live_simulated_channel_no_send_2026_06_09 import _api_key_from_env  # noqa: E402


def _config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v1",
        publish_state="published",
        agent_name="Generic Assistant",
        persona="warm, direct human advisor for a generic product line",
        instructions=(
            "Help the customer move forward using configured capabilities for "
            "exact sourced facts. Keep messages short and human."
        ),
        language="es",
        tone="brief, warm, human",
        kb_snippets=[
            {
                "source_id": "kb-general-overview",
                "title": "General overview",
                "excerpt": "A standard and a premium option exist; exact data "
                "comes from the verification system.",
            }
        ],
        tool_bindings=[
            {
                "name": "catalog.search",
                "description": (
                    "Finds catalog options matching the customer's request and returns "
                    "their option_id values. Run this first when the customer has not "
                    "named a specific option."
                ),
                "dry_facts": {
                    "options": [
                        {"option_id": "opt-economy-1", "label": "economy option"},
                        {"option_id": "opt-standard-1", "label": "standard option"},
                    ]
                },
            },
            {
                "name": "requirements.lookup",
                "description": (
                    "Returns the factual requirement list for a validated selected option."
                ),
                "preconditions": ["selected_option"],
                "dry_facts": {
                    "requirements": [
                        "valid identification",
                        "proof of address",
                        "recent proof of income when applicable",
                    ]
                },
            },
            {
                "name": "quote.resolve",
                "description": (
                    "Returns an exact quote. Requires option_id, which comes from "
                    "catalog.search results — never invent it."
                ),
                "preconditions": ["option_id"],
                "dry_facts": {"price": 120, "currency": "USD", "billing": "monthly"},
            },
        ],
        field_definitions=[
            {"field_key": "selected_option", "required": True},
            {"field_key": "work_type", "required": False},
        ],
        handoff={"enabled": True, "targets": ["sales"]},
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


def _resolver_previews() -> list[dict]:
    resolver = RespondStyleDeploymentResolver()
    views = [
        DeploymentView(
            tenant_id="generic-tenant",
            deployment_id="dep-published",
            agent_id="agent-1",
            active_version_id="v1",
            publish_state="published",
            respond_style_enabled=True,
        ),
        DeploymentView(
            tenant_id="generic-tenant",
            deployment_id="dep-draft",
            agent_id="agent-2",
            active_version_id="v1",
            publish_state="draft",
            respond_style_enabled=True,
        ),
        DeploymentView(
            tenant_id="generic-tenant",
            deployment_id="dep-live-flags",
            agent_id="agent-3",
            active_version_id="v1",
            publish_state="published",
            respond_style_enabled=True,
            send_enabled=True,
            outbox_enabled=True,
            live_send_enabled=True,
        ),
    ]
    return [resolver.resolve(view).model_dump(mode="json") for view in views]


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "PHASE_11_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                },
                indent=2,
            )
        )
        return 0

    config = _config()
    sink = InMemoryEvidenceSink()
    lab = RespondStyleTestLabDirect(
        config=config,
        tool_loop_factory=lambda: RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=DryFactsToolExecutor(config.tool_bindings),
            config=RespondStyleToolLoopConfig(
                max_tool_rounds=3,
                max_total_tool_calls=8,
                max_elapsed_seconds=120.0,
            ),
        ),
        evidence_sink=sink,
    )
    results = await lab.run_scenarios([
        TestLabScenario(
            name="chaotic_compound",
            turns=[
                "quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta"
            ],
        ),
        TestLabScenario(
            name="sequential_two_step_price",
            turns=["cuanto cuesta la opcion mas economica que tengan?"],
        ),
    ])

    all_turns = [turn for result in results for turn in result.turns]
    rounds_used = [
        turn.trace.get("respond_style_tool_loop", {}).get("tool_rounds", 0)
        for turn in all_turns
    ]
    summaries = [
        {
            "scenario": result.scenario_name,
            "turns": [
                {
                    "turn": turn.turn_number,
                    "inbound": turn.inbound_text,
                    "final_message": turn.final_message,
                    "blocked_reason": turn.blocked_reason,
                    "tool_rounds": turn.trace.get("respond_style_tool_loop", {}).get(
                        "tool_rounds"
                    ),
                    "tools": turn.tools,
                    "provisional_field_keys": turn.provisional_field_keys,
                    "send_decision": turn.send_decision,
                }
                for turn in result.turns
            ],
        }
        for result in results
    ]
    compound_ok = any(
        turn.simulated_outbound
        and turn.trace.get("respond_style_tool_loop", {}).get("tool_rounds", 0) >= 2
        for turn in all_turns
    )
    all_no_send = all(turn.send_decision == "no_send" for turn in all_turns)
    no_blocked = all(turn.blocked_reason is None for turn in all_turns)

    resolver_previews = _resolver_previews()
    resolver_ok = (
        resolver_previews[0]["route_preview"] == "product_agent_direct"
        and resolver_previews[1]["route_preview"] == "legacy_runner"
        and all(item["send_decision"] == "no_send" for item in resolver_previews)
        and all(item["live_routing_active"] is False for item in resolver_previews)
    )

    ready = compound_ok and all_no_send and no_blocked and resolver_ok
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_11_RESPOND_STYLE_MULTIRound_TESTLAB_RESOLVER_NO_SEND_READY"
                    if ready
                    else "PHASE_11_BLOCKED_BY_MODEL_BEHAVIOR"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "compound_used_multiple_rounds": compound_ok,
                "rounds_used": rounds_used,
                "scenarios": summaries,
                "resolver_previews": resolver_previews,
                "side_effects": {
                    "outbox": False,
                    "workflows": False,
                    "actions": False,
                    "delivery": False,
                    "db_writes": False,
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

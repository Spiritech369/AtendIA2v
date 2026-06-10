"""Manual live simulator (terminal chat) over the Respond-Style direct route.

Usage (from repo root):
    core/.venv/Scripts/python tools/run_manual_live_simulator_2026_06_09.py
    ... --tenant generic_sales|generic_scheduling|generic_support
    ... --config path/to/published_config.json   (ProductAgentPublishedConfig)
    ... --script "hola||que opciones tienen?||/save||/exit"   (non-interactive)

Commands inside the chat: /exit /trace /state /save /reset

No WhatsApp, no outbox, no delivery adapter, no workflow/action execution:
replies are simulated candidates from ProductAgentRuntime (context builder
-> tool loop -> validator). State lives only in memory; /save writes
evidence reports under reports/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import (  # noqa: E402
    DryFactsToolExecutor,
    ManualLiveSimulator,
    ProductAgentPublishedConfig,
    RespondStyleLLMTurnProvider,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import (  # noqa: E402
    RespondStyleToolLoopConfig,
)

sys.path.insert(0, str(REPO_ROOT / "tools"))
from run_live_simulated_channel_no_send_2026_06_09 import _api_key_from_env  # noqa: E402


def _sales_config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-sales-tenant",
        agent_id="generic-sales-agent",
        agent_version_id="v1",
        publish_state="published_no_send",
        agent_name="Generic Sales Assistant",
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
                "source_id": "kb-overview",
                "title": "Overview",
                "excerpt": (
                    "A standard option and a premium option exist. Exact quotes "
                    "and requirement lists come from the verification system. "
                    "A human teammate is available on request."
                ),
            }
        ],
        tool_bindings=[
            {
                "name": "catalog.search",
                "description": "Finds catalog options and their option_id values.",
                "dry_facts": {
                    "options": [
                        {"option_id": "opt-standard-1", "label": "standard option"},
                        {"option_id": "opt-premium-1", "label": "premium option"},
                    ]
                },
            },
            {
                "name": "quote.resolve",
                "description": "Returns an exact quote for a validated selected option.",
                "preconditions": ["selected_option"],
                "dry_facts": {"price": 120, "currency": "USD", "billing": "monthly"},
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


def _scheduling_config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-scheduling-tenant",
        agent_id="generic-scheduling-agent",
        agent_version_id="v1",
        publish_state="published_no_send",
        agent_name="Generic Scheduling Assistant",
        persona="efficient, warm scheduling coordinator",
        instructions="Help the customer book using verified availability only.",
        language="es",
        tone="brief, warm",
        kb_snippets=[
            {
                "source_id": "kb-booking-rules",
                "title": "Booking rules",
                "excerpt": "Bookings require a service type and an available slot.",
            }
        ],
        tool_bindings=[
            {
                "name": "availability.lookup",
                "description": "Returns verified open slots for a service type.",
                "preconditions": ["service_type"],
                "dry_facts": {
                    "date_scope": "next_business_day",
                    "open_slots": ["10:00", "12:30", "16:00"],
                },
            }
        ],
        field_definitions=[
            {"field_key": "service_type", "required": True},
            {"field_key": "appointment_date", "required": True},
        ],
        workflow_bindings=[
            {
                "binding_name": "appointment_requested",
                "event_name": "appointment.requested",
                "required_fields": ["service_type", "appointment_date"],
            }
        ],
        handoff={"enabled": True, "targets": ["front_desk"]},
        hard_policies=[
            {
                "policy_id": "availability_claim_requires_support",
                "trigger_patterns": [r"\b(?:disponib|available|slot)\w*\b"],
                "requires_any": ["tool:availability.lookup", "basis:knowledge_source"],
            }
        ],
    )


def _support_config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-support-tenant",
        agent_id="generic-support-agent",
        agent_version_id="v1",
        publish_state="published_no_send",
        agent_name="Generic Support Assistant",
        persona="calm, clear support specialist",
        instructions="Resolve from verified sources; escalate when configured.",
        language="es",
        tone="calm, clear",
        kb_snippets=[
            {
                "source_id": "kb-support-faq",
                "title": "Support FAQ",
                "excerpt": "Account issues are resolved after identity confirmation.",
            }
        ],
        tool_bindings=[
            {
                "name": "faq.lookup",
                "description": "Returns verified answers from the support knowledge base.",
                "dry_facts": {
                    "answer_facts": [
                        "identity confirmation is required first",
                        "a reset link can be issued after confirmation",
                    ]
                },
            }
        ],
        field_definitions=[
            {"field_key": "issue_type", "required": True},
            {"field_key": "urgency", "required": False},
        ],
        workflow_bindings=[
            {
                "binding_name": "handoff_requested",
                "event_name": "support.handoff_requested",
                "required_fields": ["issue_type"],
            }
        ],
        handoff={"enabled": True, "targets": ["support"]},
        hard_policies=[],
    )


TENANT_CONFIGS = {
    "generic_sales": _sales_config,
    "generic_scheduling": _scheduling_config,
    "generic_support": _support_config,
}


class FileReportWriter:
    def __init__(self, reports_dir: Path) -> None:
        self._reports_dir = reports_dir

    def write(self, basename: str, *, json_text: str, md_text: str) -> list[str]:
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        json_path = self._reports_dir / f"{basename}.json"
        md_path = self._reports_dir / f"{basename}.md"
        json_path.write_text(json_text, encoding="utf-8")
        md_path.write_text(md_text, encoding="utf-8")
        return [str(json_path), str(md_path)]


def _load_config(args: argparse.Namespace) -> ProductAgentPublishedConfig:
    if args.config:
        payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
        return ProductAgentPublishedConfig.model_validate(payload)
    return TENANT_CONFIGS[args.tenant]()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant", choices=sorted(TENANT_CONFIGS), default="generic_sales"
    )
    parser.add_argument("--config", help="path to a ProductAgentPublishedConfig JSON")
    parser.add_argument(
        "--script",
        help="non-interactive input: messages/commands separated by '||'",
    )
    args = parser.parse_args()

    api_key, env_source = _api_key_from_env()
    if not api_key:
        print("MANUAL_LIVE_SIMULATOR_BLOCKED_BY_OPENAI: no API key configured")
        return 1

    config = _load_config(args)
    run_label = datetime.now().strftime("%Y_%m_%d_%H%M")
    simulator = ManualLiveSimulator(
        config=config,
        tool_loop_factory=lambda: RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=DryFactsToolExecutor(config.tool_bindings),
            config=RespondStyleToolLoopConfig(
                max_tool_rounds=3, max_elapsed_seconds=120.0
            ),
        ),
        report_writer=FileReportWriter(REPO_ROOT / "reports"),
        run_label=run_label,
    )

    print(f"manual live simulator (no_send) | agent: {config.agent_name}")
    print(f"key source: {env_source} | commands: /exit /trace /state /save /reset")
    print("-" * 60)

    scripted = args.script.split("||") if args.script else None
    while True:
        if scripted is not None:
            if not scripted:
                break
            raw = scripted.pop(0)
            print(f"you> {raw}")
        else:
            try:
                raw = input("you> ")
            except (EOFError, KeyboardInterrupt):
                raw = "/exit"
        output = await simulator.handle_input(raw)
        for line in output.lines:
            print(f"  {line}")
        if output.kind == "exit":
            if simulator.channel.records:
                for path in simulator.save_report():
                    print(f"  saved: {path}")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

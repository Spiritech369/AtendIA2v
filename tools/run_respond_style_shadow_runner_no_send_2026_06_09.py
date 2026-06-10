from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import (  # noqa: E402
    AgentContextPackage,
    AgentTurnInput,
    CurrentPathShadowOutput,
    LLMToolCallProposal,
    RespondStyleLLMTurnProvider,
    RespondStyleShadowRunner,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult  # noqa: E402


def _turn_input(
    text: str,
    *,
    conversation_id: str,
    contact_snapshot: dict[str, Any] | None = None,
) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="generic-tenant",
        deployment_id="generic-deployment",
        agent_id="generic-agent",
        agent_version_id="generic-version",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="manual_shadow_no_send",
        conversation_id=conversation_id,
        contact_id="generic-contact",
        inbound_text=text,
        contact_snapshot=contact_snapshot or {},
        recent_messages=[],
    )


def _context(*, contact_state: dict[str, Any] | None = None) -> AgentContextPackage:
    state = contact_state or {}
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
                "enabled": True,
                "capability": "resolve exact requirements when selected_option exists",
                "preconditions": ["selected_option"],
                "when_to_use": [
                    "contact_state.requested_fact is requirements",
                    "customer asks what is needed for a selected option",
                ],
                "returns": ["requirements", "source_refs"],
            },
            {
                "name": "quote.resolve",
                "enabled": True,
                "capability": "resolve exact quote when selected_option exists",
                "preconditions": ["selected_option"],
                "when_to_use": [
                    "contact_state.requested_fact is quote",
                    "customer asks exact cost for a selected option",
                ],
                "returns": ["price", "currency", "source_refs"],
            },
            {
                "name": "alternate_product_search",
                "enabled": True,
                "capability": "find lower-cost or alternate options when budget concern exists",
                "preconditions": ["budget_concern"],
                "when_to_use": ["contact_state.budget_concern is true"],
                "returns": ["options", "source_refs"],
            },
        ],
        field_policies=[
            {"field_key": "lead_intent", "writable": True},
            {"field_key": "work_type", "writable": True},
            {"field_key": "budget_concern", "writable": True},
        ],
        workflow_trigger_schemas=[],
        action_schemas=[],
        handoff_policy={"enabled": True, "targets": ["sales", "support"]},
    )


class _SnapshotCurrentPath:
    def __init__(self, final_message: str | None) -> None:
        self.final_message = final_message

    def run_current_path(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> CurrentPathShadowOutput:
        _ = turn_input
        _ = context
        if self.final_message is None:
            return CurrentPathShadowOutput(
                available=False,
                unavailable_reason="snapshot_not_available",
            )
        return CurrentPathShadowOutput(
            available=True,
            final_message=self.final_message,
            tools=[],
            field_updates=[],
            validation_result={"status": "snapshot"},
            send_decision="no_send",
        )


class _DryFactToolExecutor:
    def __init__(self) -> None:
        self.side_effects = {"outbox": False, "workflows": False, "actions": False}

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
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
        if tool_call.tool_name == "alternate_product_search":
            if not contact_state.get("budget_concern"):
                return _skipped(tool_call, "missing_budget_concern")
            return ToolExecutionResult(
                tool_name=tool_call.tool_name,
                status="succeeded",
                facts={"options": ["standard option", "lower-cost alternative"]},
                citations=["generic-alternates-source"],
                source_refs=["alternate_product_search"],
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


def _api_key_from_env(
    env_file_paths: tuple[Path, ...] | None = None,
) -> tuple[str | None, str | None]:
    for env_name in ("OPENAI_API_KEY", "ATENDIA_V2_OPENAI_API_KEY"):
        value = os.getenv(env_name)
        if value:
            return value, env_name
    paths = env_file_paths or (REPO_ROOT / ".env", CORE_ROOT / ".env")
    for path in paths:
        for env_name in ("OPENAI_API_KEY", "ATENDIA_V2_OPENAI_API_KEY"):
            value = _read_env_file_value(path, env_name)
            if value:
                return value, f"{_display_path(path)}:{env_name}"
    return None, None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _read_env_file_value(path: Path, env_name: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != env_name:
            continue
        cleaned = value.strip().strip("'\"")
        return cleaned or None
    return None


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "PHASE_6_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                    "side_effects": {"outbox": False, "workflows": False, "actions": False},
                },
                indent=2,
            )
        )
        return 0

    scenarios = [
        ("greeting", "hola", {}, "I am here to help. How can I help you?"),
        ("info", "busco info", {}, "Please provide more information."),
        ("seniority", "15 meses", {}, "Thanks, I updated your data."),
        (
            "requirements",
            "que ocupo",
            {"selected_option": "standard option", "requested_fact": "requirements"},
            "Please provide the following documents.",
        ),
        ("merchant", "soy comerciante", {"work_type": "merchant"}, "Please fill out the form."),
        ("price_objection", "esta caro", {"budget_concern": True}, "More information is needed."),
        ("robot", "eres un robot?", {}, "I am an AI assistant here to help."),
        (
            "model",
            "metro",
            {"selected_option": "metro"},
            "At your service. How can I help?",
        ),
        (
            "chaotic",
            "quiero la metro, trabajo por mi cuenta, que ocupo y cuanto doy",
            {
                "selected_option": "metro",
                "requested_fact": "requirements",
                "work_type": "self_employed",
            },
            "Please provide more information to continue.",
        ),
    ]
    results: list[dict[str, Any]] = []
    for index, (name, text, state, current_message) in enumerate(scenarios, start=1):
        runner = RespondStyleShadowRunner(
            current_path=_SnapshotCurrentPath(current_message),
            respond_style_loop=RespondStyleToolLoop(
                provider=RespondStyleLLMTurnProvider(api_key=api_key),
                executor=_DryFactToolExecutor(),
            ),
        )
        result = await runner.run(
            turn_input=_turn_input(
                text,
                conversation_id=f"shadow-{index}",
                contact_snapshot=state,
            ),
            context=_context(contact_state=state),
        )
        results.append(result.model_dump(mode="json"))

    ready = all(item["final_decision"] == "no_send" for item in results)
    ready = ready and any(
        item["respond_style_path"]["tool_results"] for item in results
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_6_RESPOND_STYLE_SHADOW_RUNNER_READY"
                    if ready
                    else "PHASE_6_BLOCKED_BY_SHADOW_COMPARISON"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "results": results,
                "side_effects": {"outbox": False, "workflows": False, "actions": False},
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

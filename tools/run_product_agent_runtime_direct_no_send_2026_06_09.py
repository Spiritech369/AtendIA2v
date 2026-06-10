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
    LLMToolCallProposal,
    ProductAgentRuntime,
    ProductAgentRuntimeInput,
    RespondStyleContextSnapshot,
    RespondStyleLLMTurnProvider,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tools"))
from run_respond_style_context_builder_no_send_2026_06_09 import (  # noqa: E402
    _sales_snapshot,
    _scheduling_snapshot,
    _support_snapshot,
)


class _StaticSnapshotAdapter:
    """Stands in for the future Product Agent config adapter (Phase 9+)."""

    def __init__(self, snapshot: RespondStyleContextSnapshot) -> None:
        self._snapshot = snapshot

    def load_snapshot(
        self, runtime_input: ProductAgentRuntimeInput
    ) -> RespondStyleContextSnapshot:
        return self._snapshot.model_copy(
            update={
                "conversation_id": runtime_input.conversation_id,
                "inbound_text": runtime_input.inbound_text,
            }
        )


class _DryFactToolExecutor:
    def __init__(self, facts_by_tool: dict[str, dict[str, Any]]) -> None:
        self._facts_by_tool = facts_by_tool
        self.calls: list[str] = []

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        self.calls.append(tool_call.tool_name)
        facts = self._facts_by_tool.get(tool_call.tool_name)
        if facts is None:
            return ToolExecutionResult(
                tool_name=tool_call.tool_name,
                status="skipped",
                error_code="tool_not_available",
                is_required=tool_call.required,
                can_support_claims=False,
            )
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="succeeded",
            facts=facts,
            citations=[f"{tool_call.tool_name}-source"],
            source_refs=[tool_call.tool_name],
            is_required=tool_call.required,
            can_support_claims=True,
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


SCENARIOS = [
    {
        "name": "generic_sales_requirements",
        "snapshot": _sales_snapshot,
        "inbound_text": "que necesito para la opcion estandar?",
        "contact_fields_update": {"product_interest": "standard option"},
        "facts_by_tool": {
            "requirements.lookup": {
                "selection": "standard option",
                "requirements": [
                    "valid identification",
                    "proof of address",
                ],
            },
            "quote.resolve": {
                "selection": "standard option",
                "price": 120,
                "currency": "USD",
            },
            "catalog.search": {"options": ["standard option", "premium option"]},
        },
    },
    {
        "name": "generic_scheduling_availability",
        "snapshot": _scheduling_snapshot,
        "inbound_text": "que horarios tienen disponibles para una consulta general?",
        "contact_fields_update": {"service_type": "general consultation"},
        "facts_by_tool": {
            "availability.lookup": {
                "service_type": "general consultation",
                "date_scope": "next_business_day",
                "open_slots": ["10:00", "12:30", "16:00"],
            },
        },
    },
    {
        "name": "generic_support_faq",
        "snapshot": _support_snapshot,
        "inbound_text": "no puedo entrar a mi cuenta, que hago?",
        "contact_fields_update": {"issue_type": "account access"},
        "facts_by_tool": {
            "faq.lookup": {
                "topic": "account access",
                "answer_facts": [
                    "identity confirmation is required first",
                    "a reset link can be issued after confirmation",
                ],
            },
        },
    },
]


def _apply_contact_fields(
    snapshot: RespondStyleContextSnapshot,
    updates: dict[str, Any],
) -> RespondStyleContextSnapshot:
    fields = []
    for field in snapshot.contact_fields:
        if field.field_key in updates:
            fields.append(field.model_copy(update={"current_value": updates[field.field_key]}))
        else:
            fields.append(field)
    return snapshot.model_copy(update={"contact_fields": fields})


async def _run_scenario(scenario: dict[str, Any], api_key: str) -> dict[str, Any]:
    snapshot = _apply_contact_fields(
        scenario["snapshot"](), scenario["contact_fields_update"]
    )
    executor = _DryFactToolExecutor(scenario["facts_by_tool"])
    runtime = ProductAgentRuntime(
        snapshot_adapter=_StaticSnapshotAdapter(snapshot),
        tool_loop=RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=executor,
        ),
    )
    result = await runtime.run_turn(
        ProductAgentRuntimeInput(
            tenant_id=snapshot.tenant_id,
            agent_id=snapshot.agent_id,
            conversation_id=f"direct-{scenario['name']}",
            contact_id=snapshot.contact_id,
            inbound_text=scenario["inbound_text"],
        )
    )
    dumped = result.model_dump(mode="json")
    return {
        "scenario": scenario["name"],
        "send_decision": result.send_decision,
        "side_effects_allowed": result.side_effects_allowed,
        "side_effects": result.side_effects,
        "blocked_reason": result.blocked_reason,
        "tools_executed": executor.calls,
        "tool_results_count": len(result.tool_results),
        "final_message": result.final_message,
        "validation_status": result.validation_result.get("status"),
        "field_update_proposals": result.field_update_proposals,
        "workflow_event_proposals": result.workflow_event_proposals,
        "handoff_proposal": result.handoff_proposal,
        "runtime_path": dumped["trace"]
        .get("respond_style_product_agent_runtime", {})
        .get("runtime_path"),
    }


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "PHASE_8_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                    "side_effects": {"outbox": False, "workflows": False, "actions": False},
                },
                indent=2,
            )
        )
        return 0

    results = [await _run_scenario(scenario, api_key) for scenario in SCENARIOS]

    # A scenario may legitimately answer from KB context without a tool
    # round; the direct tool path must be proven by at least one scenario.
    ready = all(
        item["send_decision"] == "no_send"
        and item["side_effects_allowed"] is False
        and item["blocked_reason"] is None
        and item["final_message"]
        and item["validation_status"] == "valid"
        for item in results
    ) and any(
        item["tools_executed"] and item["tool_results_count"] for item in results
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_8_PRODUCT_AGENT_RUNTIME_DIRECT_PATH_NO_SEND_READY"
                    if ready
                    else "PHASE_8_BLOCKED_BY_MODEL_BEHAVIOR"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "results": results,
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

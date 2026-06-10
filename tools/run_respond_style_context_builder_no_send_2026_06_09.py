from __future__ import annotations

import json
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
    ContactFieldState,
    RespondStyleContextPackageBuilder,
    RespondStyleContextSnapshot,
    TranscriptMessage,
)


def _sales_snapshot() -> RespondStyleContextSnapshot:
    return RespondStyleContextSnapshot(
        tenant_id="generic-sales-tenant",
        agent_id="generic-sales-agent",
        agent_version_id="v1",
        conversation_id="sales-conv-1",
        contact_id="sales-contact-1",
        inbound_text="hola, busco informacion de un producto",
        recent_messages=[
            TranscriptMessage(role="customer", text="hola", message_id="s1"),
        ],
        contact_fields=[
            ContactFieldState(field_key="product_interest", required=True),
            ContactFieldState(field_key="income_type", required=True),
            ContactFieldState(field_key="employment_seniority", required=True),
        ],
        agent_name="Generic Sales Assistant",
        agent_persona="helpful sales advisor",
        agent_instructions="Guide the customer toward a validated option using tools.",
        language="es",
        tone="brief, human",
        kb_snippets=[
            {
                "source_id": "kb-sales-overview",
                "title": "Product overview",
                "excerpt": "Options vary by validated customer profile.",
            }
        ],
        tool_bindings=[
            {
                "name": "catalog.search",
                "description": "Finds catalog options matching structured filters.",
            },
            {
                "name": "quote.resolve",
                "description": "Returns an exact quote for a validated selection.",
                "preconditions": ["product_interest"],
            },
            {
                "name": "requirements.lookup",
                "description": "Returns factual requirements for a validated selection.",
                "preconditions": ["product_interest"],
            },
        ],
        workflow_bindings=[
            {
                "binding_name": "ready_for_handoff",
                "event_name": "lead.ready_for_handoff",
                "required_fields": ["product_interest", "income_type"],
            }
        ],
        handoff={"enabled": True, "targets": ["sales"]},
        hard_policies=[
            {
                "policy_id": "price_claim_requires_support",
                "trigger_patterns": [r"\$\s*\d", r"\b\d[\d,.]*\s*(?:mil\s+)?(?:mxn|pesos?)\b"],
                "requires_any": ["tool:quote.resolve", "basis:knowledge_source"],
            },
            {
                "policy_id": "requirements_claim_requires_support",
                "trigger_patterns": [r"\b(?:requisitos?|requirements?)\b"],
                "requires_any": ["tool:requirements.lookup", "basis:knowledge_source"],
            },
        ],
    )


def _scheduling_snapshot() -> RespondStyleContextSnapshot:
    return RespondStyleContextSnapshot(
        tenant_id="generic-scheduling-tenant",
        agent_id="generic-scheduling-agent",
        agent_version_id="v1",
        conversation_id="schedule-conv-1",
        contact_id="schedule-contact-1",
        inbound_text="quiero agendar una cita",
        contact_fields=[
            ContactFieldState(field_key="appointment_date", required=True),
            ContactFieldState(field_key="service_type", required=True),
        ],
        agent_name="Generic Scheduling Assistant",
        agent_persona="efficient scheduling coordinator",
        agent_instructions="Help the customer book using verified availability only.",
        language="es",
        tone="brief, warm",
        kb_snippets=[
            {
                "source_id": "kb-scheduling-rules",
                "title": "Booking rules",
                "excerpt": "Bookings require a service type and an available slot.",
            }
        ],
        tool_bindings=[
            {
                "name": "availability.lookup",
                "description": "Returns verified open slots for a service type.",
                "preconditions": ["service_type"],
            }
        ],
        workflow_bindings=[
            {
                "binding_name": "appointment_requested",
                "event_name": "appointment.requested",
                "required_fields": ["appointment_date", "service_type"],
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


def _support_snapshot() -> RespondStyleContextSnapshot:
    return RespondStyleContextSnapshot(
        tenant_id="generic-support-tenant",
        agent_id="generic-support-agent",
        agent_version_id="v1",
        conversation_id="support-conv-1",
        contact_id="support-contact-1",
        inbound_text="tengo un problema con mi cuenta",
        contact_fields=[
            ContactFieldState(field_key="issue_type", required=True),
            ContactFieldState(field_key="urgency", required=False),
        ],
        agent_name="Generic Support Assistant",
        agent_persona="calm support specialist",
        agent_instructions="Resolve from verified sources; escalate when configured.",
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
            },
            {
                "name": "ticket.create",
                "description": "Creates a follow-up ticket (dry-run only in no-send).",
                "dry_run_only": True,
                "approval_required": True,
            },
        ],
        action_bindings=[
            {
                "action_name": "ticket.create",
                "description": "Creates a follow-up ticket in the helpdesk.",
            }
        ],
        workflow_bindings=[
            {
                "binding_name": "handoff_requested",
                "event_name": "support.handoff_requested",
                "required_fields": ["issue_type"],
            }
        ],
        handoff={"enabled": True, "targets": ["support"]},
        hard_policies=[
            {
                "policy_id": "resolution_claim_requires_support",
                "trigger_patterns": [r"\b(?:resuelto|resolved|solucionado)\b"],
                "requires_any": ["tool:faq.lookup", "basis:knowledge_source"],
            }
        ],
    )


def _verify(name: str, snapshot: RespondStyleContextSnapshot) -> dict[str, Any]:
    built = RespondStyleContextPackageBuilder().build(snapshot)
    turn_input = built.turn_input
    package = built.context_package

    assert isinstance(turn_input, AgentTurnInput)
    assert isinstance(package, AgentContextPackage)
    AgentContextPackage.model_validate(package.model_dump(mode="json"))
    AgentTurnInput.model_validate(turn_input.model_dump(mode="json"))

    serialized = built.model_dump_json()
    checks = {
        "turn_input_valid": True,
        "context_package_valid": True,
        "send_mode": turn_input.send_mode,
        "runtime_path": turn_input.trace_context.get("runtime_path"),
        "tool_count": len(package.tool_schemas),
        "tools_all_no_customer_copy": all(
            item.get("no_customer_copy") is True for item in package.tool_schemas
        ),
        "workflows_all_dry_run_no_side_effects": all(
            item.get("dry_run_only") is True
            and item.get("side_effects_allowed") is False
            for item in package.workflow_trigger_schemas
        ),
        "actions_all_no_side_effects": all(
            item.get("side_effects_allowed") is False
            for item in package.action_schemas
        ),
        "kb_snippets_have_source_id": all(
            item.get("source_id") for item in package.retrieved_context
        ),
        "hard_policy_count": len(package.hard_policies),
        "missing_fields_as_data": [
            item["field_key"]
            for item in package.field_policies
            if item.get("missing") is True
        ],
        "no_final_message": "final_message" not in package.model_dump(mode="json"),
        "no_question_fields": (
            "next_best_question" not in serialized
            and "suggested_question" not in serialized
            and "pending_slot" not in serialized
        ),
        "handoff_message_authored_by_llm": package.handoff_policy.get(
            "customer_message_authored_by_llm"
        )
        is True,
    }
    return {"tenant": name, **checks}


def main() -> int:
    results = [
        _verify("generic_sales", _sales_snapshot()),
        _verify("generic_scheduling", _scheduling_snapshot()),
        _verify("generic_support", _support_snapshot()),
    ]
    ready = all(
        item["turn_input_valid"]
        and item["context_package_valid"]
        and item["send_mode"] == "no_send"
        and item["tools_all_no_customer_copy"]
        and item["workflows_all_dry_run_no_side_effects"]
        and item["actions_all_no_side_effects"]
        and item["kb_snippets_have_source_id"]
        and item["no_final_message"]
        and item["no_question_fields"]
        and item["handoff_message_authored_by_llm"]
        for item in results
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_7_RESPOND_STYLE_CONTEXT_PACKAGE_BUILDER_READY"
                    if ready
                    else "PHASE_7_BLOCKED_BY_PRODUCT_AGENT_CONFIG"
                ),
                "mode": "no_send",
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
    raise SystemExit(main())

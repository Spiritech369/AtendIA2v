from __future__ import annotations

import re
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    ContactFieldState,
    ContextSnapshotError,
    RespondStyleContextPackageBuilder,
    RespondStyleContextSnapshot,
    RespondStyleTurnValidator,
    TranscriptMessage,
)

BUILDER_SOURCE = Path("core/atendia/agent_runtime/respond_style_context_builder.py")


def _snapshot(**overrides) -> RespondStyleContextSnapshot:
    base = {
        "tenant_id": "generic-tenant",
        "agent_id": "generic-agent",
        "agent_version_id": "generic-version-1",
        "conversation_id": "conv-1",
        "contact_id": "contact-1",
        "inbound_text": "hola",
        "recent_messages": [
            TranscriptMessage(role="customer", text="first inbound", message_id="m1"),
            TranscriptMessage(role="assistant", text="first reply", message_id="m2"),
            TranscriptMessage(role="customer", text="second inbound", message_id="m3"),
        ],
        "contact_fields": [
            ContactFieldState(
                field_key="service_interest",
                current_value="general",
                required=True,
            ),
            ContactFieldState(field_key="preferred_schedule", required=True),
        ],
        "agent_name": "Generic Assistant",
        "agent_persona": "professional and friendly advisor",
        "agent_instructions": "Help the customer using configured capabilities only.",
        "language": "es",
        "tone": "brief, human",
        "goals": ["resolve the customer request"],
        "do_not_do": ["do not invent facts"],
        "kb_snippets": [
            {
                "source_id": "kb-general-info",
                "title": "General info",
                "excerpt": "The team can verify exact data on request.",
            }
        ],
        "tool_bindings": [
            {
                "name": "requirements.lookup",
                "description": "Returns factual requirements for a validated selection.",
                "preconditions": ["selected_option"],
                "output_facts_schema": {"requirements": "list[string]"},
            }
        ],
        "action_bindings": [
            {
                "action_name": "ticket.create",
                "description": "Creates a follow-up ticket.",
            }
        ],
        "workflow_bindings": [
            {
                "binding_name": "ready_for_handoff",
                "event_name": "lead.ready_for_handoff",
                "required_fields": ["service_interest"],
            }
        ],
        "handoff": {"enabled": True, "targets": ["support"]},
        "hard_policies": [
            {
                "policy_id": "price_claim_requires_support",
                "trigger_patterns": [r"\$\s*\d"],
                "requires_any": ["tool:quote.resolve", "basis:knowledge_source"],
            }
        ],
    }
    base.update(overrides)
    return RespondStyleContextSnapshot(**base)


def test_builder_produces_valid_turn_input() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    assert isinstance(built.turn_input, AgentTurnInput)
    assert built.turn_input.tenant_id == "generic-tenant"
    assert built.turn_input.send_mode == "no_send"
    assert built.turn_input.runtime_mode == "test_lab_no_send"
    assert built.turn_input.trace_context["runtime_path"] == "respond_style_no_send"


def test_builder_produces_valid_context_package() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    assert isinstance(built.context_package, AgentContextPackage)
    # The package round-trips through the contract's strict schema.
    AgentContextPackage.model_validate(built.context_package.model_dump(mode="json"))


def test_transcript_keeps_order_and_structure() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    messages = built.turn_input.recent_messages
    assert [m["message_id"] for m in messages] == ["m1", "m2", "m3"]
    assert [m["role"] for m in messages] == ["customer", "assistant", "customer"]
    assert all("text" in m and "attachments" in m for m in messages)


def test_transcript_role_aliases_normalize() -> None:
    message = TranscriptMessage(role="inbound", text="hello")
    assert message.role == "customer"
    message = TranscriptMessage(role="agent", text="hello")
    assert message.role == "assistant"


def test_agent_config_is_included_verbatim() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    identity = built.context_package.agent_identity
    assert identity["name"] == "Generic Assistant"
    assert identity["persona"] == "professional and friendly advisor"
    assert identity["language"] == "es"
    assert identity["goals"] == ["resolve the customer request"]
    assert identity["do_not_do"] == ["do not invent facts"]
    assert built.context_package.instructions == (
        "Help the customer using configured capabilities only."
    )


def test_known_and_missing_fields_are_data_not_questions() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    identity = built.context_package.agent_identity
    assert identity["contact_state"] == {"service_interest": "general"}
    assert identity["missing_fields"] == ["preferred_schedule"]

    policies = {item["field_key"]: item for item in built.context_package.field_policies}
    assert policies["service_interest"]["missing"] is False
    assert policies["preferred_schedule"]["missing"] is True
    assert policies["preferred_schedule"]["can_propose_update"] is True
    # No question text anywhere in the field policy payload.
    assert "?" not in str(built.context_package.field_policies)


def test_tool_schemas_expose_capability_metadata() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    tool = built.context_package.tool_schemas[0]
    assert tool["tool_name"] == "requirements.lookup"
    assert tool["preconditions"] == ["selected_option"]
    assert tool["output_facts_schema"] == {"requirements": "list[string]"}
    assert tool["produces_claim_support"] is True
    assert tool["no_customer_copy"] is True
    assert tool["enabled"] is True
    assert tool["binding_id"]


def test_workflows_default_to_dry_run_and_no_side_effects() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    workflow = built.context_package.workflow_trigger_schemas[0]
    assert workflow["binding_name"] == "ready_for_handoff"
    assert workflow["dry_run_only"] is True
    assert workflow["approval_required"] is True
    assert workflow["side_effects_allowed"] is False


def test_workflow_side_effects_forced_off_in_no_send() -> None:
    built = RespondStyleContextPackageBuilder().build(
        _snapshot(
            workflow_bindings=[
                {
                    "binding_name": "ready_for_handoff",
                    "event_name": "lead.ready_for_handoff",
                    "side_effects_allowed": True,
                }
            ]
        )
    )

    assert built.context_package.workflow_trigger_schemas[0]["side_effects_allowed"] is False


def test_actions_default_to_no_side_effects() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    action = built.context_package.action_schemas[0]
    assert action["action_name"] == "ticket.create"
    assert action["dry_run_only"] is True
    assert action["approval_required"] is True
    assert action["side_effects_allowed"] is False


def test_kb_snippets_require_stable_source_id() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    snippet = built.context_package.retrieved_context[0]
    assert snippet["source_id"] == "kb-general-info"
    assert snippet["citation"]
    assert built.context_package.knowledge_bindings[0]["source_id"] == "kb-general-info"

    with pytest.raises(ContextSnapshotError) as excinfo:
        RespondStyleContextPackageBuilder().build(
            _snapshot(kb_snippets=[{"title": "no id", "excerpt": "text"}])
        )
    assert excinfo.value.code == "kb_snippet_missing_source_id"


def test_kb_source_ids_are_claim_validatable() -> None:
    from atendia.agent_runtime import LLMAgentTurnOutput, LLMClaim

    built = RespondStyleContextPackageBuilder().build(_snapshot())
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="The team can verify exact data on request.",
            claims=[
                LLMClaim(
                    text="The team can verify exact data on request.",
                    basis="knowledge_source",
                    source_refs=["kb-general-info"],
                )
            ],
            confidence=0.8,
        ),
        context=built.context_package,
    )
    assert decision.send_decision == "send"


def test_hard_policies_pass_through_and_malformed_fails_closed() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())
    policy = built.context_package.hard_policies[0]
    assert policy["policy_id"] == "price_claim_requires_support"
    assert policy["requires_any"] == ["tool:quote.resolve", "basis:knowledge_source"]

    with pytest.raises(ContextSnapshotError) as excinfo:
        RespondStyleContextPackageBuilder().build(
            _snapshot(hard_policies=[{"policy_id": "broken", "trigger_patterns": []}])
        )
    assert excinfo.value.code == "hard_policy_malformed"


def test_handoff_policy_has_no_customer_copy() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    handoff = built.context_package.handoff_policy
    assert handoff["enabled"] is True
    assert handoff["targets"] == ["support"]
    assert handoff["customer_message_authored_by_llm"] is True
    assert "message" not in handoff
    assert "text" not in handoff


def test_builder_generates_no_final_message_or_question_fields() -> None:
    built = RespondStyleContextPackageBuilder().build(_snapshot())

    serialized = built.model_dump_json()
    assert "final_message" not in built.context_package.model_dump(mode="json")
    assert "next_best_question" not in serialized
    assert "suggested_question" not in serialized
    assert "pending_slot" not in serialized


def test_send_policy_carries_mode_and_scope_without_deciding_send() -> None:
    built = RespondStyleContextPackageBuilder().build(
        _snapshot(publish_state="published", send_scope={"allowlist": ["contact-1"]})
    )

    send_policy = built.context_package.send_policy
    assert send_policy["send_mode"] == "no_send"
    assert send_policy["publish_state"] == "published"
    assert send_policy["send_scope"] == {"allowlist": ["contact-1"]}
    assert "send_decision" not in send_policy


def test_builder_source_has_no_unsafe_legacy_or_live_imports() -> None:
    source = BUILDER_SOURCE.read_text(encoding="utf-8")

    forbidden = [
        "ConversationRunner",
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
        "SendAdapter",
        "outbox",
        "enqueue_messages",
        "evaluate_event",
        "AgentService",
        "advisor_pipeline",
        "validated_response_plan",
    ]
    assert not any(term in source for term in forbidden)


def test_builder_source_has_no_tenant_or_vertical_hardcode() -> None:
    lowered = BUILDER_SOURCE.read_text(encoding="utf-8").casefold()

    forbidden_terms = [
        "dinamo",
        "motos",
        "credito",
        "credit",
        "sat",
        "metro",
        "barber",
        "dentist",
    ]
    assert not any(
        re.search(rf"\b{re.escape(term)}\b", lowered) for term in forbidden_terms
    )


def test_builder_source_has_no_conversational_string_literals() -> None:
    source = BUILDER_SOURCE.read_text(encoding="utf-8")
    literals = re.findall(r'"([^"\n]*)"', source)
    for literal in literals:
        # No question marks, greetings, or sentence-like customer copy in code.
        assert "?" not in literal
        assert "¿" not in literal and "¡" not in literal
        assert not literal.casefold().startswith(("hola", "hello", "hi ", "gracias"))


def test_builder_does_not_route_tools_by_customer_phrases() -> None:
    source = BUILDER_SOURCE.read_text(encoding="utf-8")
    assert "inbound_text" not in source.replace(
        "inbound_text=snapshot.inbound_text", ""
    ).replace("inbound_text: str", "").replace("inbound_text\n", "")

"""Customer Copy Kill Map — hard-block battery for the Product Agent direct route.

Each test maps to a "required blocking test" row in
docs/architecture/customer_copy_kill_map.md. The battery proves that the
published-Product-Agent direct route cannot reach any legacy customer-copy
source: not by convention, but by import graph and by output structure.
"""

from __future__ import annotations

import pytest

from atendia.agent_runtime import (
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMHandoffProposal,
    LLMWorkflowEventProposal,
    ProductAgentRuntime,
    ProductAgentRuntimeInput,
    RespondStyleContextSnapshot,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_llm_provider import blocked_provider_decision
from atendia.agent_runtime.respond_style_route_audit import audit_direct_route_imports

# Canned legacy copy that must never be authored by the direct route.
LEGACY_CANNED_PHRASES = [
    "Necesito que una persona del equipo revise esto",
    "Dime qué dato quieres revisar",
    "Para darte la lista exacta dime",
    "Sí se puede revisar",
]


def test_published_product_agent_route_never_imports_legacy_copy_sources() -> None:
    """Kill map: published_product_agent_never_enters_conversation_runner,
    structured_runtime_composer_blocked, human_response_composer_blocked,
    progress/quote/mandatory guard blocks, provider fallback block,
    send_adapter/outbox isolation, workflow copy block.

    Transitive import-graph proof: importing the WHOLE direct route in a
    fresh interpreter must not load any legacy copy-producing module.
    Shared with Publish Control via respond_style_route_audit.
    """
    violations = audit_direct_route_imports()
    assert violations == [], (
        "Direct route transitively imports legacy copy sources: " f"{violations}"
    )


class _StaticAdapter:
    def __init__(self, snapshot: RespondStyleContextSnapshot) -> None:
        self._snapshot = snapshot

    def load_snapshot(self, runtime_input):
        return self._snapshot


class _ScriptedProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)

    async def generate(self, *, turn_input, context) -> FinalTurnDecision:
        return self._decisions.pop(0)


class _NeverCalledExecutor:
    def execute_tool(self, tool_call, context):  # pragma: no cover - guard
        raise AssertionError("executor must not be called")


def _snapshot() -> RespondStyleContextSnapshot:
    return RespondStyleContextSnapshot(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v1",
        conversation_id="conv-1",
        inbound_text="hola",
        workflow_bindings=[
            {"binding_name": "ready_for_handoff", "event_name": "lead.ready"}
        ],
        handoff={"enabled": True, "targets": ["support"]},
    )


def _runtime(decisions: list[FinalTurnDecision]) -> ProductAgentRuntime:
    return ProductAgentRuntime(
        snapshot_adapter=_StaticAdapter(_snapshot()),
        tool_loop=RespondStyleToolLoop(
            provider=_ScriptedProvider(decisions),
            executor=_NeverCalledExecutor(),
        ),
    )


def _runtime_input() -> ProductAgentRuntimeInput:
    return ProductAgentRuntimeInput(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        conversation_id="conv-1",
        inbound_text="hola",
    )


@pytest.mark.asyncio
async def test_blocked_turn_yields_no_fallback_copy() -> None:
    """Kill map: advisor_pipeline_fallback_is_no_send_for_product_agent,
    provider_fallback_visible_copy_blocks_send, manual_recovery_never_visible.

    A blocked/failed turn must surface as no_send with final_message=None —
    never replaced by canned recovery copy."""
    blocked = blocked_provider_decision("llm_turn_provider_failed", "Boom")
    result = await _runtime([blocked]).run_turn(_runtime_input())

    assert result.send_decision == "no_send"
    assert result.final_message is None
    serialized = result.model_dump_json()
    for phrase in LEGACY_CANNED_PHRASES:
        assert phrase not in serialized


@pytest.mark.asyncio
async def test_handoff_proposal_does_not_override_final_message() -> None:
    """Kill map: handoff_proposal_does_not_override_final_message."""
    message = "Te comunico con el equipo."
    decision = FinalTurnDecision(
        final_message=message,
        send_decision="no_send",
        validation=AgentTurnValidationResult(status="valid", send_decision="no_send"),
        accepted_handoff=LLMHandoffProposal(
            needed=True, reason="customer asked", target="support"
        ),
    )
    result = await _runtime([decision]).run_turn(_runtime_input())

    assert result.final_message == message
    assert result.handoff_proposal is not None
    assert result.handoff_proposal["target"] == "support"
    # The handoff proposal carries no visible-copy fields at all.
    assert set(result.handoff_proposal) == {"needed", "reason", "target", "priority"}


@pytest.mark.asyncio
async def test_workflow_proposals_cannot_author_visible_copy() -> None:
    """Kill map: workflow_customer_copy_blocked_for_product_agent.

    Workflow proposals are structured events; the visible message remains
    exclusively the LLM decision's final_message."""
    message = "Listo, registro tu solicitud."
    decision = FinalTurnDecision(
        final_message=message,
        send_decision="no_send",
        validation=AgentTurnValidationResult(
            status="valid",
            send_decision="no_send",
            accepted_workflow_events=[
                LLMWorkflowEventProposal(
                    binding_name="ready_for_handoff",
                    event_name="lead.ready",
                    reason="ready",
                )
            ],
        ),
        accepted_workflow_events=[
            LLMWorkflowEventProposal(
                binding_name="ready_for_handoff",
                event_name="lead.ready",
                reason="ready",
            )
        ],
    )
    result = await _runtime([decision]).run_turn(_runtime_input())

    assert result.final_message == message
    proposal = result.workflow_event_proposals[0]
    assert "final_message" not in proposal
    assert "message" not in proposal
    assert "text" not in proposal


@pytest.mark.asyncio
async def test_validated_response_plan_artifacts_never_appear() -> None:
    """Kill map: validated_response_plan_not_visible_copy_authority.

    No pending_slot / next_best_question / suggested_question artifact can
    appear anywhere in a direct-route result."""
    decision = FinalTurnDecision(
        final_message="Hola, te ayudo.",
        send_decision="no_send",
        validation=AgentTurnValidationResult(status="valid", send_decision="no_send"),
    )
    result = await _runtime([decision]).run_turn(_runtime_input())

    serialized = result.model_dump_json()
    assert "pending_slot" not in serialized
    assert "next_best_question" not in serialized
    assert "suggested_question" not in serialized

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    ContactFieldState,
    FinalTurnDecision,
    LLMFieldUpdateProposal,
    LLMHandoffProposal,
    LLMToolCallProposal,
    LLMWorkflowEventProposal,
    ProductAgentRuntime,
    ProductAgentRuntimeInput,
    ProductAgentRuntimeResult,
    RespondStyleContextSnapshot,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult

RUNTIME_SOURCE = Path(
    "core/atendia/agent_runtime/respond_style_product_agent_runtime.py"
)


class _FakeSnapshotAdapter:
    def __init__(self, snapshot: RespondStyleContextSnapshot) -> None:
        self._snapshot = snapshot
        self.calls: list[ProductAgentRuntimeInput] = []

    def load_snapshot(
        self, runtime_input: ProductAgentRuntimeInput
    ) -> RespondStyleContextSnapshot:
        self.calls.append(runtime_input)
        return self._snapshot


class _FakeTurnProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)
        self.contexts: list[AgentContextPackage] = []
        self.turn_inputs: list[AgentTurnInput] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        self.turn_inputs.append(turn_input)
        self.contexts.append(context)
        return self._decisions.pop(0)


class _FakeToolExecutor:
    def __init__(self, results: list[ToolExecutionResult]) -> None:
        self._results = list(results)
        self.calls: list[LLMToolCallProposal] = []

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        self.calls.append(tool_call)
        return self._results.pop(0)


def _runtime_input(**overrides) -> ProductAgentRuntimeInput:
    base = {
        "tenant_id": "generic-tenant",
        "agent_id": "generic-agent",
        "conversation_id": "conv-1",
        "contact_id": "contact-1",
        "inbound_text": "what do I need?",
    }
    base.update(overrides)
    return ProductAgentRuntimeInput(**base)


def _snapshot(**overrides) -> RespondStyleContextSnapshot:
    base = {
        "tenant_id": "generic-tenant",
        "agent_id": "generic-agent",
        "agent_version_id": "v1",
        "conversation_id": "conv-1",
        "contact_id": "contact-1",
        "inbound_text": "what do I need?",
        "agent_name": "Generic Assistant",
        "agent_instructions": "Use configured capabilities only.",
        "contact_fields": [
            ContactFieldState(field_key="service_interest", required=True),
        ],
        "tool_bindings": [
            {
                "name": "requirements.lookup",
                "description": "Returns factual requirements for a validated selection.",
            }
        ],
        "workflow_bindings": [
            {
                "binding_name": "ready_for_handoff",
                "event_name": "lead.ready_for_handoff",
            }
        ],
        "handoff": {"enabled": True, "targets": ["support"]},
    }
    base.update(overrides)
    return RespondStyleContextSnapshot(**base)


def _valid_decision(
    final_message: str | None,
    tool_requests: list[LLMToolCallProposal],
    **decision_overrides,
) -> FinalTurnDecision:
    validation = AgentTurnValidationResult(
        status="valid",
        accepted_tool_requests=tool_requests,
        send_decision="no_send",
    )
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=validation,
        **decision_overrides,
    )


def _runtime(provider, executor, adapter) -> ProductAgentRuntime:
    return ProductAgentRuntime(
        snapshot_adapter=adapter,
        tool_loop=RespondStyleToolLoop(provider=provider, executor=executor),
    )


@pytest.mark.asyncio
async def test_direct_path_runs_builder_and_tool_loop_no_send() -> None:
    adapter = _FakeSnapshotAdapter(_snapshot())
    tool_call = LLMToolCallProposal(
        tool_name="requirements.lookup", reason="customer asked"
    )
    provider = _FakeTurnProvider([
        _valid_decision(None, [tool_call]),
        _valid_decision("You need an ID and proof of address.", []),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="succeeded",
            facts={"requirements": ["ID", "proof of address"]},
            source_refs=["requirements.lookup"],
        )
    ])

    result = await _runtime(provider, executor, adapter).run_turn(_runtime_input())

    assert isinstance(result, ProductAgentRuntimeResult)
    assert result.send_decision == "no_send"
    assert result.final_message == "You need an ID and proof of address."
    assert result.agent_version_id == "v1"
    assert result.tool_results[0]["tool_name"] == "requirements.lookup"
    assert result.side_effects_allowed is False
    assert result.side_effects == {
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }
    # The builder ran: the provider saw a built context with the bound tool.
    assert provider.contexts[0].tool_schemas[0]["tool_name"] == "requirements.lookup"
    assert provider.contexts[0].tool_schemas[0]["no_customer_copy"] is True
    assert provider.turn_inputs[0].trace_context["runtime_path"] == "respond_style_no_send"


@pytest.mark.asyncio
async def test_runtime_input_rejects_live_mode_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ProductAgentRuntimeInput(
            tenant_id="generic-tenant",
            agent_id="generic-agent",
            conversation_id="conv-1",
            inbound_text="hello",
            requested_mode="live_candidate",
        )


@pytest.mark.asyncio
async def test_snapshot_with_live_send_mode_is_blocked() -> None:
    adapter = _FakeSnapshotAdapter(
        _snapshot(send_mode="live_candidate", runtime_mode="live_candidate")
    )
    provider = _FakeTurnProvider([])
    executor = _FakeToolExecutor([])

    result = await _runtime(provider, executor, adapter).run_turn(_runtime_input())

    assert result.send_decision == "no_send"
    assert result.blocked_reason == "send_mode_not_no_send"
    assert result.final_message is None
    assert provider.contexts == []


@pytest.mark.asyncio
async def test_snapshot_with_live_runtime_mode_is_blocked() -> None:
    adapter = _FakeSnapshotAdapter(_snapshot(runtime_mode="live_limited"))
    provider = _FakeTurnProvider([])
    executor = _FakeToolExecutor([])

    result = await _runtime(provider, executor, adapter).run_turn(_runtime_input())

    assert result.blocked_reason == "runtime_mode_not_no_send"
    assert provider.contexts == []


@pytest.mark.asyncio
async def test_snapshot_adapter_failure_fails_closed() -> None:
    class _BrokenAdapter:
        def load_snapshot(self, runtime_input):
            raise RuntimeError("config unavailable")

    provider = _FakeTurnProvider([])
    executor = _FakeToolExecutor([])

    result = await _runtime(provider, executor, _BrokenAdapter()).run_turn(
        _runtime_input()
    )

    assert result.send_decision == "no_send"
    assert result.blocked_reason == "snapshot_adapter_failed:RuntimeError"


@pytest.mark.asyncio
async def test_malformed_snapshot_config_fails_closed() -> None:
    adapter = _FakeSnapshotAdapter(
        _snapshot(kb_snippets=[{"title": "no source id", "excerpt": "text"}])
    )
    provider = _FakeTurnProvider([])
    executor = _FakeToolExecutor([])

    result = await _runtime(provider, executor, adapter).run_turn(_runtime_input())

    assert result.send_decision == "no_send"
    assert result.blocked_reason == "kb_snippet_missing_source_id"


@pytest.mark.asyncio
async def test_proposals_are_propagated_not_executed() -> None:
    adapter = _FakeSnapshotAdapter(_snapshot())
    decision = _valid_decision(
        "Noted, I will pass this along.",
        [],
        accepted_field_writes=[
            LLMFieldUpdateProposal(
                field_key="service_interest",
                value="general",
                evidence=["customer message"],
                confidence=0.9,
                reason="customer stated interest",
            )
        ],
        accepted_workflow_events=[
            LLMWorkflowEventProposal(
                binding_name="ready_for_handoff",
                event_name="lead.ready_for_handoff",
                reason="customer is ready",
            )
        ],
        accepted_handoff=LLMHandoffProposal(
            needed=True, reason="human review", target="support"
        ),
    )
    provider = _FakeTurnProvider([decision])
    executor = _FakeToolExecutor([])

    result = await _runtime(provider, executor, adapter).run_turn(_runtime_input())

    assert result.field_update_proposals[0]["field_key"] == "service_interest"
    assert result.workflow_event_proposals[0]["event_name"] == "lead.ready_for_handoff"
    assert result.handoff_proposal == {
        "needed": True,
        "reason": "human review",
        "target": "support",
        "priority": "normal",
    }
    # Proposals only: nothing was executed or persisted.
    assert executor.calls == []
    assert result.side_effects["field_writes"] is False
    assert result.side_effects["workflows"] is False


@pytest.mark.asyncio
async def test_blocked_tool_loop_decision_propagates_reason() -> None:
    tool_call = LLMToolCallProposal(
        tool_name="requirements.lookup", reason="customer asked"
    )
    adapter = _FakeSnapshotAdapter(_snapshot())
    provider = _FakeTurnProvider([_valid_decision(None, [tool_call])])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="failed",
            error_code="upstream_unavailable",
        )
    ])

    result = await _runtime(provider, executor, adapter).run_turn(_runtime_input())

    assert result.send_decision == "no_send"
    assert result.final_message is None
    assert result.blocked_reason == "required_tool_failed:upstream_unavailable"


def test_result_model_refuses_send_decision() -> None:
    with pytest.raises(ValidationError):
        ProductAgentRuntimeResult(
            run_id="r1",
            tenant_id="t",
            agent_id="a",
            conversation_id="c",
            send_decision="send",
        )
    with pytest.raises(ValidationError):
        ProductAgentRuntimeResult(
            run_id="r1",
            tenant_id="t",
            agent_id="a",
            conversation_id="c",
            side_effects_allowed=True,
        )


def test_runtime_source_has_no_unsafe_legacy_or_live_imports() -> None:
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")

    forbidden = [
        "ConversationRunner",
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
        "ValidatedResponsePlan",
        "SendAdapter",
        "outbox",
        "enqueue_messages",
        "evaluate_event",
        "AgentService",
        "advisor_pipeline",
        "composer",
    ]
    assert not any(term in source for term in forbidden)


def test_runtime_source_has_no_tenant_or_vertical_hardcode() -> None:
    lowered = RUNTIME_SOURCE.read_text(encoding="utf-8").casefold()

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


def test_runtime_source_does_not_route_by_customer_phrases() -> None:
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")
    # The runtime never inspects inbound_text content.
    assert "inbound_text" not in source.replace(
        "inbound_text: str", ""
    ).replace('"inbound_text"', "").replace("runtime input text field", "")

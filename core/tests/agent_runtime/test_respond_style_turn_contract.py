from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from atendia.agent_runtime import (
    AgentTurnRetryInstruction,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMAgentTurnOutput,
    LLMFieldUpdateProposal,
    LLMToolCallProposal,
    LLMWorkflowEventProposal,
    ValidationErrorItem,
)


def test_llm_agent_turn_output_requires_final_message() -> None:
    with pytest.raises(ValidationError):
        LLMAgentTurnOutput(final_message="", confidence=0.5)

    output = LLMAgentTurnOutput(
        final_message="I can help with that.",
        confidence=0.8,
    )

    assert output.final_message == "I can help with that."
    assert output.tool_requests == []


def test_tool_call_proposal_schema() -> None:
    proposal = LLMToolCallProposal(
        tool_name="catalog.lookup",
        arguments={"query": "entry-level option"},
        reason="The customer asked for available products.",
    )

    assert proposal.tool_name == "catalog.lookup"
    assert proposal.required is True


def test_field_update_proposal_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        LLMFieldUpdateProposal(
            field_key="preferred_service",
            value="maintenance",
            evidence=[],
            confidence=0.9,
            reason="The customer requested maintenance.",
        )

    proposal = LLMFieldUpdateProposal(
        field_key="preferred_service",
        value="maintenance",
        evidence=["I need maintenance."],
        confidence=0.9,
        reason="The customer requested maintenance.",
    )

    assert proposal.evidence == ["I need maintenance."]


def test_workflow_event_proposal_requires_binding_name() -> None:
    with pytest.raises(ValidationError):
        LLMWorkflowEventProposal(
            binding_name=" ",
            event_name="lead.ready_for_review",
            payload={"priority": "normal"},
            reason="The customer requested follow-up.",
        )

    proposal = LLMWorkflowEventProposal(
        binding_name="lead_review",
        event_name="lead.ready_for_review",
        payload={"priority": "normal"},
        reason="The customer requested follow-up.",
    )

    assert proposal.binding_name == "lead_review"


def test_validation_result_retry_instruction() -> None:
    error = ValidationErrorItem(
        code="missing_required_tool",
        message="A required tool was not requested.",
        retryable=True,
    )
    result = AgentTurnValidationResult(
        status="invalid_retryable",
        retryable=True,
        feedback_for_llm="Request the required tool, then answer from its result.",
        blocked_items=[error],
    )
    instruction = AgentTurnRetryInstruction(
        attempt_number=1,
        max_attempts=2,
        feedback_for_llm=result.feedback_for_llm or "",
        error_items=result.blocked_items,
    )

    assert result.retryable is True
    assert instruction.error_items[0].code == "missing_required_tool"


def test_validation_result_retry_requires_feedback() -> None:
    with pytest.raises(ValidationError):
        AgentTurnValidationResult(status="invalid_retryable", retryable=True)


def test_final_turn_decision_no_send_default() -> None:
    decision = FinalTurnDecision()

    assert decision.send_decision == "no_send"
    assert decision.final_message is None


def test_final_turn_decision_send_requires_valid_validation() -> None:
    with pytest.raises(ValidationError):
        FinalTurnDecision(final_message="Ready.", send_decision="send")

    valid = AgentTurnValidationResult(status="valid", send_decision="send")
    decision = FinalTurnDecision(
        final_message="Ready.",
        send_decision="send",
        validation=valid,
    )

    assert decision.final_message == "Ready."
    assert decision.send_decision == "send"


def test_contract_has_no_tenant_or_vertical_hardcode() -> None:
    source = Path(
        "core/atendia/agent_runtime/respond_style_turn_contract.py"
    ).read_text(encoding="utf-8")
    lowered = source.casefold()

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
        re.search(rf"\b{re.escape(term)}\b", lowered)
        for term in forbidden_terms
    )


def test_tool_request_turn_allows_null_final_message() -> None:
    from atendia.agent_runtime import LLMToolCallProposal

    output = LLMAgentTurnOutput(
        turn_kind="tool_request",
        final_message=None,
        tool_requests=[
            LLMToolCallProposal(
                tool_name="requirements.lookup",
                reason="Customer asked for the exact list.",
            )
        ],
        confidence=0.8,
    )

    assert output.final_message is None
    assert output.turn_kind == "tool_request"


def test_tool_request_turn_rejects_customer_copy() -> None:
    import pytest
    from atendia.agent_runtime import LLMToolCallProposal

    with pytest.raises(ValueError):
        LLMAgentTurnOutput(
            turn_kind="tool_request",
            final_message="Let me check the documents you need.",
            tool_requests=[
                LLMToolCallProposal(
                    tool_name="requirements.lookup",
                    reason="Customer asked for the exact list.",
                )
            ],
            confidence=0.8,
        )


def test_tool_request_turn_requires_at_least_one_tool() -> None:
    import pytest

    with pytest.raises(ValueError):
        LLMAgentTurnOutput(
            turn_kind="tool_request",
            final_message=None,
            confidence=0.8,
        )


def test_handoff_request_turn_requires_needed_proposal() -> None:
    import pytest
    from atendia.agent_runtime import LLMHandoffProposal

    with pytest.raises(ValueError):
        LLMAgentTurnOutput(
            turn_kind="handoff_request",
            final_message=None,
            confidence=0.8,
        )

    output = LLMAgentTurnOutput(
        turn_kind="handoff_request",
        final_message=None,
        handoff_proposal=LLMHandoffProposal(
            needed=True,
            reason="Human review is required.",
            target="specialist",
        ),
        confidence=0.8,
    )
    assert output.turn_kind == "handoff_request"


def test_final_response_still_requires_final_message() -> None:
    import pytest

    with pytest.raises(ValueError):
        LLMAgentTurnOutput(
            turn_kind="final_response",
            final_message="   ",
            confidence=0.8,
        )

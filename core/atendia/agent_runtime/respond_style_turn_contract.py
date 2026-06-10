from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JsonDict = dict[str, Any]

RuntimeMode = Literal[
    "test_lab_no_send",
    "readiness_no_send",
    "live_candidate",
    "live_limited",
    "paused",
]
SendMode = Literal["no_send", "live_candidate", "live_limited"]
ValidationStatus = Literal["valid", "invalid_retryable", "blocked"]
FinalSendDecision = Literal["no_send", "send", "handoff"]
TurnKind = Literal["tool_request", "final_response", "handoff_request"]


def _not_blank(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank")
    return cleaned


class AgentTurnInput(BaseModel):
    """Normalized input for a Product-First agent turn."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    deployment_id: str
    agent_id: str
    agent_version_id: str
    runtime_mode: RuntimeMode
    send_mode: SendMode = "no_send"
    channel: str
    conversation_id: str
    contact_id: str | None = None
    inbound_event_id: str | None = None
    inbound_text: str
    attachments: list[JsonDict] = Field(default_factory=list)
    recent_messages: list[JsonDict] = Field(default_factory=list)
    contact_snapshot: JsonDict = Field(default_factory=dict)
    conversation_snapshot: JsonDict = Field(default_factory=dict)
    trace_context: JsonDict = Field(default_factory=dict)

    @field_validator(
        "tenant_id",
        "deployment_id",
        "agent_id",
        "agent_version_id",
        "runtime_mode",
        "send_mode",
        "channel",
        "conversation_id",
        "inbound_text",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="text field")


class AgentContextPackage(BaseModel):
    """Published agent context passed into an LLM turn."""

    model_config = ConfigDict(extra="forbid")

    agent_identity: JsonDict = Field(default_factory=dict)
    instructions: str = ""
    voice_guide: JsonDict = Field(default_factory=dict)
    knowledge_bindings: list[JsonDict] = Field(default_factory=list)
    retrieved_context: list[JsonDict] = Field(default_factory=list)
    tool_schemas: list[JsonDict] = Field(default_factory=list)
    tool_results: list[JsonDict] = Field(default_factory=list)
    field_policies: list[JsonDict] = Field(default_factory=list)
    action_schemas: list[JsonDict] = Field(default_factory=list)
    workflow_trigger_schemas: list[JsonDict] = Field(default_factory=list)
    handoff_policy: JsonDict = Field(default_factory=dict)
    send_policy: JsonDict = Field(default_factory=dict)
    hard_policies: list[JsonDict] = Field(default_factory=list)
    validator_feedback: list[JsonDict] = Field(default_factory=list)


class LLMToolCallProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: JsonDict = Field(default_factory=dict)
    reason: str
    required: bool = True

    @field_validator("tool_name", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="tool proposal text")


class LLMFieldUpdateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str
    value: Any
    evidence: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    reason: str

    @field_validator("field_key", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="field proposal text")

    @field_validator("evidence")
    @classmethod
    def require_evidence_text(cls, value: list[str]) -> list[str]:
        return [_not_blank(item, field_name="field evidence") for item in value]


class LLMActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_name: str
    payload: JsonDict = Field(default_factory=dict)
    reason: str
    requires_approval: bool = True

    @field_validator("action_name", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="action proposal text")


class LLMWorkflowEventProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_name: str
    event_name: str
    payload: JsonDict = Field(default_factory=dict)
    reason: str

    @field_validator("binding_name", "event_name", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="workflow proposal text")


class LLMHandoffProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needed: bool = False
    reason: str | None = None
    target: str | None = None
    priority: Literal["low", "normal", "high"] = "normal"

    @model_validator(mode="after")
    def require_reason_when_needed(self) -> Self:
        if self.needed:
            self.reason = _not_blank(self.reason or "", field_name="handoff reason")
        return self


class LLMClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    basis: Literal["tool_result", "knowledge_source", "customer_message", "agent_policy"]
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="claim text")


class LLMAgentTurnOutput(BaseModel):
    """LLM-authored turn proposal before AtendIA validation.

    Turn kinds:
    - ``tool_request``: the LLM needs fact tools before answering. It must
      propose at least one tool and must NOT contain customer copy.
    - ``final_response``: visible customer copy; ``final_message`` required.
    - ``handoff_request``: requires a needed handoff proposal; an optional
      visible message may accompany it and is validated as customer copy.
    """

    model_config = ConfigDict(extra="forbid")

    turn_kind: TurnKind = "final_response"
    final_message: str | None = None
    tool_requests: list[LLMToolCallProposal] = Field(default_factory=list)
    field_write_proposals: list[LLMFieldUpdateProposal] = Field(default_factory=list)
    action_proposals: list[LLMActionProposal] = Field(default_factory=list)
    workflow_event_proposals: list[LLMWorkflowEventProposal] = Field(default_factory=list)
    handoff_proposal: LLMHandoffProposal | None = None
    claims: list[LLMClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    needs_retry_reason: str | None = None

    @model_validator(mode="after")
    def validate_turn_kind_shape(self) -> Self:
        message = (self.final_message or "").strip()
        if self.turn_kind == "tool_request":
            if message:
                raise ValueError("tool_request turns must not contain customer copy")
            if not self.tool_requests:
                raise ValueError("tool_request turns require at least one tool request")
            self.final_message = None
        elif self.turn_kind == "handoff_request":
            if self.handoff_proposal is None or not self.handoff_proposal.needed:
                raise ValueError("handoff_request turns require a needed handoff proposal")
            self.final_message = message or None
        else:
            self.final_message = _not_blank(message, field_name="final_message")
        return self


class ValidationErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    path: str | None = None
    retryable: bool = False
    metadata: JsonDict = Field(default_factory=dict)

    @field_validator("code", "message")
    @classmethod
    def require_text(cls, value: str) -> str:
        return _not_blank(value, field_name="validation error text")


class AgentTurnRetryInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    feedback_for_llm: str
    error_items: list[ValidationErrorItem] = Field(min_length=1)

    @field_validator("feedback_for_llm")
    @classmethod
    def require_feedback(cls, value: str) -> str:
        return _not_blank(value, field_name="feedback_for_llm")

    @model_validator(mode="after")
    def attempts_must_be_possible(self) -> Self:
        if self.attempt_number > self.max_attempts:
            raise ValueError("attempt_number cannot exceed max_attempts")
        if not any(item.retryable for item in self.error_items):
            raise ValueError("retry instruction requires at least one retryable error")
        return self


class AgentTurnValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ValidationStatus
    retryable: bool = False
    feedback_for_llm: str | None = None
    accepted_tool_requests: list[LLMToolCallProposal] = Field(default_factory=list)
    accepted_field_writes: list[LLMFieldUpdateProposal] = Field(default_factory=list)
    accepted_actions: list[LLMActionProposal] = Field(default_factory=list)
    accepted_workflow_events: list[LLMWorkflowEventProposal] = Field(default_factory=list)
    blocked_items: list[ValidationErrorItem] = Field(default_factory=list)
    send_decision: FinalSendDecision = "no_send"
    blocked_reason: str | None = None

    @model_validator(mode="after")
    def validate_status_shape(self) -> Self:
        if self.status == "valid":
            if self.blocked_items:
                raise ValueError("valid result cannot contain blocked_items")
            if self.retryable:
                raise ValueError("valid result cannot be retryable")
        if self.status == "invalid_retryable":
            if not self.retryable:
                raise ValueError("invalid_retryable result must be retryable")
            self.feedback_for_llm = _not_blank(
                self.feedback_for_llm or "",
                field_name="feedback_for_llm",
            )
        if self.status == "blocked":
            if self.retryable:
                raise ValueError("blocked result cannot be retryable")
            self.blocked_reason = _not_blank(
                self.blocked_reason or "",
                field_name="blocked_reason",
            )
            self.send_decision = "no_send"
        return self


class FinalTurnDecision(BaseModel):
    """Final validated turn decision. Defaults to fail-closed no-send."""

    model_config = ConfigDict(extra="forbid")

    final_message: str | None = None
    send_decision: FinalSendDecision = "no_send"
    validation: AgentTurnValidationResult | None = None
    accepted_field_writes: list[LLMFieldUpdateProposal] = Field(default_factory=list)
    accepted_actions: list[LLMActionProposal] = Field(default_factory=list)
    accepted_workflow_events: list[LLMWorkflowEventProposal] = Field(default_factory=list)
    retry_instruction: AgentTurnRetryInstruction | None = None
    trace_metadata: JsonDict = Field(default_factory=dict)

    @model_validator(mode="after")
    def fail_closed_unless_send_is_fully_valid(self) -> Self:
        if self.send_decision == "send":
            self.final_message = _not_blank(
                self.final_message or "",
                field_name="final_message",
            )
            if self.validation is None or self.validation.status != "valid":
                raise ValueError("send decision requires a valid validation result")
        if self.retry_instruction is not None:
            self.send_decision = "no_send"
        return self


__all__ = [
    "AgentContextPackage",
    "AgentTurnInput",
    "AgentTurnRetryInstruction",
    "AgentTurnValidationResult",
    "FinalTurnDecision",
    "LLMActionProposal",
    "LLMAgentTurnOutput",
    "LLMClaim",
    "LLMFieldUpdateProposal",
    "LLMHandoffProposal",
    "LLMToolCallProposal",
    "LLMWorkflowEventProposal",
    "TurnKind",
    "ValidationErrorItem",
]


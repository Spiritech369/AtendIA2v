from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from atendia.contracts.conversation_state import ConversationState
from atendia.contracts.nlu_result import NLUResult
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.contracts.vision_result import VisionResult

EvidenceType = Literal[
    "catalog_match",
    "catalog_unique_match",
    "last_question",
    "pending_field",
    "history",
    "customer_state",
    "document_state",
    "vision",
    "tool_result",
    "tenant_config",
]


class Evidence(BaseModel):
    type: EvidenceType
    source: str
    value: Any | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResolverAttempt(BaseModel):
    resolver: str
    input: str
    understood_as: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    can_write_state: bool = False
    requires_confirmation: bool = False
    field_updates: dict[str, Any] = Field(default_factory=dict)
    next_action: str | None = None
    suggested_clarification: str | None = None
    blocked_reason: str | None = None


class FinalDecisionPayload(BaseModel):
    decision: str
    field_updated: str | None = None
    value: Any | None = None
    evidence: str | None = None
    next_action: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    requires_confirmation: bool = False
    suggested_clarification: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnResolverResult(BaseModel):
    resolved: bool = False
    selected_attempt: ResolverAttempt | None = None
    attempts: list[ResolverAttempt] = Field(default_factory=list)
    field_updates: dict[str, Any] = Field(default_factory=dict)
    action_override: str | None = None
    effective_intent: str | None = None
    requires_confirmation: bool = False
    suggested_clarification: str | None = None
    final_decision_payload: FinalDecisionPayload | None = None

    def approved_field_updates(self) -> dict[str, Any]:
        attempt = self.selected_attempt
        if (
            not self.resolved
            or attempt is None
            or not attempt.can_write_state
            or attempt.requires_confirmation
        ):
            return {}
        return dict(self.field_updates or attempt.field_updates)


class TurnResolverInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    tenant_id: UUID
    conversation_id: UUID
    inbound_text: str
    nlu: NLUResult
    state: ConversationState
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    history: list[tuple[str, str]] = Field(default_factory=list)
    pipeline: PipelineDefinition
    pending_confirmation: str | None = None
    vision_result: VisionResult | None = None
    current_stage: str

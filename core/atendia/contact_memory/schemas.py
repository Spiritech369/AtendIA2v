from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FieldUpdateSource = Literal[
    "customer_message",
    "ai_inference",
    "knowledge",
    "action",
    "human",
    "workflow",
    "vision",
]
FieldUpdateStatus = Literal["suggested", "auto_applied", "rejected", "needs_review"]
FieldWritePolicy = Literal["ai_auto", "ai_suggest", "human_only"]


class ContactMemoryPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extractable_by_ai: bool = True
    write_policy: FieldWritePolicy = "ai_suggest"
    confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    evidence_required: bool = True
    prompt_visible: bool = True
    lifecycle_relevant: bool = False
    pii: bool = False
    sensitive: bool = False


class ContactMemoryWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    customer_id: UUID
    field_key: str
    new_value: Any
    source: FieldUpdateSource = "ai_inference"
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    evidence_message_id: UUID | None = None
    evidence_attachment_id: UUID | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    trace_id: str | None = None
    created_by: str | None = "agent_runtime_v2"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactMemoryDecision(BaseModel):
    field_key: str
    old_value: str | None = None
    new_value: str | None = None
    status: FieldUpdateStatus
    reason: str
    confidence: float
    evidence_id: UUID | None = None
    suggestion_id: UUID | None = None
    applied: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

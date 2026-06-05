from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LifecycleUpdateSource = Literal["agent", "workflow", "human", "system", "api"]


class LifecycleStage(BaseModel):
    id: str
    key: str
    name: str
    description: str | None = None
    goal: str | None = None
    entry_conditions: list[dict[str, Any]] = Field(default_factory=list)
    exit_conditions: list[dict[str, Any]] = Field(default_factory=list)
    recommended_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    sla_policy: dict[str, Any] = Field(default_factory=dict)
    automation_policy: dict[str, Any] = Field(default_factory=dict)
    is_lost_stage: bool = False
    order: int = 0
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class LifecycleStageUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    conversation_id: UUID
    target_stage: str
    reason: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    source: LifecycleUpdateSource = "agent"
    trace_id: str | None = None
    created_by: str | None = "agent_runtime_v2"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LifecycleDecision(BaseModel):
    conversation_id: UUID
    from_stage: str | None = None
    to_stage: str | None = None
    valid: bool
    applied: bool = False
    reason: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    history_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

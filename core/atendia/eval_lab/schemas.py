from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.schemas import (
    ActionRequest,
    FieldUpdate,
    KnowledgeCitation,
    LifecycleUpdate,
    MessageContext,
    TurnOutput,
)

JsonDict = dict[str, Any]


class EvalScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    vertical: str | None = None
    input_message: str
    conversation_history: list[MessageContext] = Field(default_factory=list)
    contact_fields: JsonDict = Field(default_factory=dict)
    lifecycle_stage: str | None = None
    knowledge_sources: list[KnowledgeCitation] = Field(default_factory=list)
    expected_behaviors: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    expected_field_updates: list[str] = Field(default_factory=list)
    expected_lifecycle: str | None = None
    expected_actions: list[str] = Field(default_factory=list)
    tenant_id: str = "00000000-0000-4000-8000-000000000001"
    conversation_id: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class EvalScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scorer: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    message: str = ""
    metadata: JsonDict = Field(default_factory=dict)


class EvalScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str
    passed: bool
    output: TurnOutput | None = None
    scores: list[EvalScore] = Field(default_factory=list)
    error: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class EvalRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    total: int
    passed_count: int
    failed_count: int
    results: list[EvalScenarioResult] = Field(default_factory=list)
    metadata: JsonDict = Field(default_factory=dict)


class ExpectedTurnOutput(BaseModel):
    """Fixture helper for scenario authors.

    This is intentionally separate from runtime execution. It lets tests and
    offline scenario files declare expected output shapes without becoming a
    second production response contract.
    """

    model_config = ConfigDict(extra="forbid")

    final_message: str
    actions: list[ActionRequest] = Field(default_factory=list)
    field_updates: list[FieldUpdate] = Field(default_factory=list)
    lifecycle_update: LifecycleUpdate | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human: bool = False
    risk_flags: list[str] = Field(default_factory=list)


ScoreStatus = Literal["pass", "fail"]

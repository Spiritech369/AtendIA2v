from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

SimulationMode = Literal["dry_run", "simulation_preview", "simulation_apply"]
SimulationStatus = Literal["pending", "running", "passed", "failed", "completed"]
ProviderName = Literal["mock", "local_deterministic", "openai"]


class SimulationRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    agent_id: UUID
    name: str
    mode: SimulationMode = "simulation_apply"
    source: str
    status: SimulationStatus = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    score: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationCase(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    case_id: str
    title: str
    category: str
    status: SimulationStatus = "pending"
    score: float | None = None
    conversation_id: UUID | None = None
    expected_final_stage: str | None = None
    expected_fields: dict[str, Any] = Field(default_factory=dict)
    expected_handoff: bool = False
    expected_documents: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationTurn(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    turn_index: int
    customer_message: str
    expected_behavior: str | None = None
    actual_final_message: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    field_updates: list[dict[str, Any]] = Field(default_factory=list)
    lifecycle_update: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    policy_result: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    trace_id: UUID | None = None
    score: float = 0.0
    pass_fail: Literal["pass", "fail"] = "fail"
    failure_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationCaseFixture(BaseModel):
    case_id: str
    title: str
    category: str
    initial_stage: str = "nuevos"
    initial_contact_fields: dict[str, Any] = Field(default_factory=dict)
    turns: list[dict[str, Any]]
    expected_field_updates: dict[str, Any] = Field(default_factory=dict)
    expected_stage_changes: list[str] = Field(default_factory=list)
    expected_handoff: bool = False
    expected_documents: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    scoring_rules: list[str] = Field(default_factory=list)


class SimulationFixture(BaseModel):
    name: str
    tenant: str = "Dinamo Motos NL"
    global_forbidden_behaviors: list[str] = Field(default_factory=list)
    cases: list[SimulationCaseFixture]

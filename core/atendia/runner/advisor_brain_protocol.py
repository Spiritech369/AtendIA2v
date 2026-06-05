from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdvisorBrainInput(_StrictModel):
    tenant_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    agent_persona: str
    user_message: str
    recent_history: list[str] = Field(default_factory=list)
    conversation_summary: str | None = None
    current_stage: str
    last_bot_message: str | None = None
    last_bot_question: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    contact_fields: dict[str, Any] = Field(default_factory=dict)
    missing_contact_fields: list[str] = Field(default_factory=list)
    pending_field: str | None = None
    seniority_evidence: str | None = None
    active_quote: dict[str, Any] | None = None
    last_quote_signature: str | None = None
    catalog_context: dict[str, Any] = Field(default_factory=dict)
    credit_options: list[dict[str, Any]] = Field(default_factory=list)
    requirements_context: dict[str, Any] = Field(default_factory=dict)
    documents_state: dict[str, Any] = Field(default_factory=dict)
    attachment_context: dict[str, Any] = Field(default_factory=dict)
    operational_risk_flags: list[str] = Field(default_factory=list)
    business_rules: dict[str, Any] = Field(default_factory=dict)
    hard_guardrails: list[str] = Field(default_factory=list)


class AdvisorBrainToolRequest(_StrictModel):
    tool_name: Literal[
        "resolve_catalog_model",
        "resolve_credit_plan",
        "compute_quote",
        "lookup_requirements",
        "get_missing_documents",
        "classify_attachment",
        "request_handoff",
    ]
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str


class AdvisorBrainStateWritePlan(_StrictModel):
    new_facts_to_write: dict[str, Any] = Field(default_factory=dict)
    corrected_facts: dict[str, Any] = Field(default_factory=dict)
    facts_requiring_confirmation: dict[str, Any] = Field(default_factory=dict)
    facts_to_leave_unchanged: list[str] = Field(default_factory=list)


class AgentBrainPlanUnderstanding(_StrictModel):
    customer_message_summary: str = ""
    detected_intents: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    context_resolution: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0, le=1)


class AgentBrainCommercialGoal(_StrictModel):
    current_goal: str = ""
    next_required_step: str = ""
    reason: str = ""


class AgentBrainToolPlanStep(_StrictModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    reason: str = ""


class AgentBrainPlan(_StrictModel):
    understanding: AgentBrainPlanUnderstanding
    commercial_goal: AgentBrainCommercialGoal
    tool_plan: list[AgentBrainToolPlanStep] = Field(default_factory=list)
    proposed_state_updates: dict[str, Any] = Field(default_factory=dict)
    proposed_pipeline_update: str | None = None
    proposed_final_action: str | None = None
    proposed_final_action_payload: dict[str, Any] = Field(default_factory=dict)
    customer_response_goal: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    needs_human_handoff: bool = False


class AdvisorBrainOutput(_StrictModel):
    customer_understanding: str
    conversation_memory_used: list[str] = Field(default_factory=list)
    detected_intent: str
    known_facts: dict[str, Any] = Field(default_factory=dict)
    new_facts_to_write: dict[str, Any] = Field(default_factory=dict)
    corrected_facts: dict[str, Any] = Field(default_factory=dict)
    missing_required_facts: list[str] = Field(default_factory=list)
    next_human_step: str
    tool_requests: list[AdvisorBrainToolRequest] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    natural_response: str
    confidence: float = Field(ge=0, le=1)
    handoff_required: bool = False
    handoff_reason: str | None = None
    state_write_plan: AdvisorBrainStateWritePlan
    trace_reasoning_summary: str
    plan: AgentBrainPlan | None = None


class AdvisorBrainMode(str, Enum):
    SHADOW = "shadow"
    PRIMARY = "primary"


class AdvisorBrainResult(_StrictModel):
    output: AdvisorBrainOutput | None = None
    llm_error: str | None = None
    validation_error: str | None = None
    guardrail_blocked: bool = False
    guardrail_reason: str | None = None
    fallback_used: bool = False
    final_response_source: Literal[
        "advisor_brain",
        "current_runner",
        "fallback_composer",
        "scripted_composer",
    ]


__all__ = [
    "AgentBrainCommercialGoal",
    "AgentBrainPlan",
    "AgentBrainPlanUnderstanding",
    "AgentBrainToolPlanStep",
    "AdvisorBrainInput",
    "AdvisorBrainMode",
    "AdvisorBrainOutput",
    "AdvisorBrainResult",
    "AdvisorBrainStateWritePlan",
    "AdvisorBrainToolRequest",
]

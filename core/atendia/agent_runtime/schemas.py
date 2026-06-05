from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonDict = dict[str, Any]

CUSTOMER_VISIBLE_TEXT_KEYS = {
    "final_message",
    "final_text",
    "message",
    "messages",
    "public_message",
    "reply",
    "text",
    "visible_text",
}


def customer_visible_text_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in CUSTOMER_VISIBLE_TEXT_KEYS:
                paths.append(path)
            paths.extend(customer_visible_text_paths(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(customer_visible_text_paths(nested, prefix=path))
    return paths


class MessageContext(BaseModel):
    role: Literal["customer", "agent", "system"]
    text: str
    sent_at: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class CustomerContext(BaseModel):
    id: str | None = None
    name: str | None = None
    phone_e164: str | None = None
    email: str | None = None
    attrs: JsonDict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ContactFieldDefinitionContext(BaseModel):
    key: str
    label: str
    field_type: str
    options: JsonDict | None = None


class LifecycleContext(BaseModel):
    stage: str | None = None
    status: str | None = None
    pipeline_id: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class ConversationMemoryContext(BaseModel):
    summary: str | None = None
    salient_facts: JsonDict = Field(default_factory=dict)
    last_quote_snapshot: JsonDict | None = None
    last_pending_question: str | None = None
    documents: JsonDict = Field(default_factory=dict)
    metadata: JsonDict = Field(default_factory=dict)


class TenantRuntimeConfigContext(BaseModel):
    ruleset: JsonDict = Field(default_factory=dict)
    tools: JsonDict = Field(default_factory=dict)
    default_voice: JsonDict = Field(default_factory=dict)
    knowledge_sources: list[str] = Field(default_factory=list)
    metadata: JsonDict = Field(default_factory=dict)
    tenant_domain_contract: JsonDict = Field(default_factory=dict)
    domain: str | None = None
    field_metadata: JsonDict = Field(default_factory=dict)
    tool_metadata: JsonDict = Field(default_factory=dict)
    pipeline_metadata: JsonDict = Field(default_factory=dict)
    workflow_event_metadata: JsonDict = Field(default_factory=dict)
    guard_metadata: JsonDict = Field(default_factory=dict)
    frontend_metadata: JsonDict = Field(default_factory=dict)
    safe_mode: bool = False


class ActiveAgentContext(BaseModel):
    id: str | None = None
    name: str | None = None
    role: str | None = None
    behavior_mode: str | None = None
    instructions: str | None = None
    tone: str | None = None
    voice: JsonDict = Field(default_factory=dict)
    language_policy: JsonDict = Field(default_factory=dict)
    enabled_knowledge_source_ids: list[str] | None = None
    enabled_action_ids: list[str] | None = None
    visible_contact_field_keys: list[str] | None = None
    allowed_lifecycle_stage_ids: list[str] | None = None
    escalation_policy: JsonDict = Field(default_factory=dict)
    metadata: JsonDict = Field(default_factory=dict)


class KnowledgeCitation(BaseModel):
    source_id: str
    title: str | None = None
    snippet: str | None = None
    score: float | None = None
    metadata: JsonDict = Field(default_factory=dict)


class TurnInput(BaseModel):
    tenant_id: str
    conversation_id: str
    inbound_text: str
    turn_number: int | None = None
    metadata: JsonDict = Field(default_factory=dict)


class TurnContext(BaseModel):
    tenant_id: str
    conversation_id: str
    inbound_text: str
    customer: CustomerContext = Field(default_factory=CustomerContext)
    messages: list[MessageContext] = Field(default_factory=list)
    contact_fields: list[ContactFieldDefinitionContext] = Field(default_factory=list)
    lifecycle: LifecycleContext = Field(default_factory=LifecycleContext)
    memory: ConversationMemoryContext = Field(default_factory=ConversationMemoryContext)
    tenant_config: TenantRuntimeConfigContext = Field(default_factory=TenantRuntimeConfigContext)
    active_agent: ActiveAgentContext | None = None
    knowledge_citations: list[KnowledgeCitation] = Field(default_factory=list)
    metadata: JsonDict = Field(default_factory=dict)


class AdvisorBrainToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    payload: JsonDict = Field(default_factory=dict)
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    required: bool = True
    metadata: JsonDict = Field(default_factory=dict)


class AdvisorBrainStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["contact_field", "lifecycle", "memory", "none"]
    key: str | None = None
    value: Any = None
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    metadata: JsonDict = Field(default_factory=dict)


class AdvisorBrainDecision(BaseModel):
    """Model-authored conversation direction, not customer-visible copy."""

    model_config = ConfigDict(extra="forbid")

    understanding: str
    customer_goal: str | None = None
    conversation_goals: list[str] = Field(default_factory=list)
    known_facts: JsonDict = Field(default_factory=dict)
    missing_facts: list[str] = Field(default_factory=list)
    next_best_action: str
    required_tools: list[AdvisorBrainToolRequest] = Field(default_factory=list)
    proposed_state_changes: list[AdvisorBrainStateChange] = Field(default_factory=list)
    response_plan: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_human: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    latest_customer_act: str | None = None
    new_information_detected: bool = False
    answered_slot: str | None = None
    should_ask_question: bool = False
    question_slot: str | None = None
    conversation_progress_action: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    """Structured tool result. Tools must not return final visible response text."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: Literal["succeeded", "skipped", "failed", "blocked"]
    data: JsonDict = Field(default_factory=dict)
    error: str | None = None
    trace_metadata: JsonDict = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_customer_visible_text(self) -> Self:
        forbidden_paths = sorted(customer_visible_text_paths(self.data))
        if forbidden_paths:
            raise ValueError(
                "ToolExecutionResult.data cannot contain customer-visible text paths: "
                + ", ".join(forbidden_paths)
            )
        return self


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    payload: JsonDict = Field(default_factory=dict)
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    idempotency_key: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Machine-readable result from an action.

    Actions must not return final customer copy. Extra fields are forbidden so
    values like ``final_message`` or ``visible_text`` are rejected at the schema
    boundary.
    """

    model_config = ConfigDict(extra="forbid")

    action_name: str
    status: Literal["succeeded", "skipped", "failed"]
    data: JsonDict = Field(default_factory=dict)
    error: str | None = None
    trace_metadata: JsonDict = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_customer_visible_text(self) -> Self:
        forbidden_paths = sorted(customer_visible_text_paths(self.data))
        if forbidden_paths:
            raise ValueError(
                "ActionResult.data cannot contain customer-visible text paths: "
                + ", ".join(forbidden_paths)
            )
        return self


class ActionDefinition(BaseModel):
    id: str | None = None
    name: str
    description: str
    input_schema: JsonDict = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    execution_mode: Literal["dry_run", "execute", "human_approval"] = "dry_run"
    sensitive: bool = False
    requires_evidence: bool = False
    requires_approval: bool = False
    enabled: bool = True
    metadata: JsonDict = Field(default_factory=dict)


class FieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str
    value: Any
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    source: Literal[
        "customer_message",
        "ai_inference",
        "knowledge",
        "action",
        "human",
        "workflow",
        "vision",
    ] = "ai_inference"
    evidence_message_id: str | None = None
    evidence_attachment_id: str | None = None
    trace_id: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class LifecycleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_stage: str | None = None
    target_status: str | None = None
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    source: Literal["agent", "workflow", "human", "system", "api"] = "agent"
    trace_id: str | None = None
    metadata: JsonDict = Field(default_factory=dict)


class TurnOutput(BaseModel):
    """Single authority for the result of one agent turn."""

    model_config = ConfigDict(extra="forbid")

    final_message: str = ""
    actions: list[ActionRequest] = Field(default_factory=list)
    field_updates: list[FieldUpdate] = Field(default_factory=list)
    lifecycle_update: LifecycleUpdate | None = None
    knowledge_citations: list[KnowledgeCitation] = Field(default_factory=list)
    confidence: float = 0.0
    needs_human: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    trace_metadata: JsonDict = Field(default_factory=dict)

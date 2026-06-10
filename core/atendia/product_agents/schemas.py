from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="custom", max_length=40)
    tone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default="es", max_length=20)
    instructions: str | None = None


class ProductAgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=40)
    tone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=20)
    instructions: str | None = None


class ProductAgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    role: str
    status: str
    tone: str | None
    language: str | None
    system_prompt: str | None
    ops_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AgentVersionCreate(BaseModel):
    role: str | None = Field(default=None, max_length=80)
    tone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=20)
    instructions: str | None = None
    prompt_blocks: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_policy: dict[str, Any] = Field(default_factory=dict)
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    action_policy: dict[str, Any] = Field(default_factory=dict)
    field_policy: dict[str, Any] = Field(default_factory=dict)
    workflow_policy: dict[str, Any] = Field(default_factory=dict)
    safety_policy: dict[str, Any] = Field(default_factory=dict)
    test_policy: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    change_summary: str | None = None


class AgentVersionUpdate(BaseModel):
    role: str | None = Field(default=None, max_length=80)
    tone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=20)
    instructions: str | None = None
    prompt_blocks: list[dict[str, Any]] | None = None
    knowledge_policy: dict[str, Any] | None = None
    tool_policy: dict[str, Any] | None = None
    action_policy: dict[str, Any] | None = None
    field_policy: dict[str, Any] | None = None
    workflow_policy: dict[str, Any] | None = None
    safety_policy: dict[str, Any] | None = None
    test_policy: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    change_summary: str | None = None


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_id: UUID
    version_number: int
    status: str
    is_immutable: bool
    role: str | None
    tone: str | None
    language: str | None
    instructions: str | None
    prompt_blocks: list[Any]
    snapshot: dict[str, Any]
    change_summary: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentDeploymentCreate(BaseModel):
    agent_id: UUID
    name: str = Field(min_length=1, max_length=160)
    channel: str = Field(default="test_lab", max_length=40)
    environment: str = Field(default="no_send", max_length=40)
    active_version_id: UUID | None = None


class AgentDeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_id: UUID
    active_version_id: UUID | None
    rollback_version_id: UUID | None
    name: str
    channel: str
    environment: str
    publish_state: str
    runtime_mode: str
    send_scope: str
    send_enabled: bool
    outbox_enabled: bool
    live_send_enabled: bool
    single_contact_smoke_enabled: bool
    actions_enabled: bool
    workflow_events_enabled: bool
    workflow_side_effects_enabled: bool
    canary_enabled: bool
    open_production_enabled: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentDeploymentTransitionRequest(BaseModel):
    to_state: str = Field(min_length=1, max_length=40)
    reason: str | None = None


class AgentPublishRequestCreate(BaseModel):
    agent_version_id: UUID
    requested_state: str = Field(default="published_no_send", max_length=40)
    send_scope: str = Field(default="none", max_length=80)
    channel_scope: str | None = Field(default=None, max_length=80)
    audience_scope: dict[str, Any] = Field(default_factory=dict)
    rollback_version_id: UUID | None = None
    approval_text: str | None = None


class AgentPublishRequestDecision(BaseModel):
    approval_text: str | None = None
    reason: str | None = None


class AgentPublishRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    deployment_id: UUID
    requested_state: str
    status: str
    send_scope: str
    channel_scope: str | None
    audience_scope: dict[str, Any]
    test_run_ids: list[Any]
    readiness_snapshot: dict[str, Any]
    blockers: list[Any]
    rollback_version_id: UUID | None
    approval_text: str | None
    decision_reason: str | None
    requested_by_user_id: UUID | None
    approved_by_user_id: UUID | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ToolBindingCreate(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required: bool = False


class ActionBindingCreate(BaseModel):
    action_key: str = Field(min_length=1, max_length=160)
    enabled: bool = False
    execution_mode: str = "disabled"
    permissions: dict[str, Any] = Field(default_factory=dict)


class AgentToolBindingCreate(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    required: bool = False


class AgentActionBindingCreate(BaseModel):
    action_key: str = Field(min_length=1, max_length=160)
    enabled: bool = False
    execution_mode: str = "disabled"
    permissions: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceBindingCreate(BaseModel):
    knowledge_source_id: UUID


class AgentKnowledgeBindingCreate(BaseModel):
    knowledge_source_id: UUID
    binding_mode: str = Field(default="answer_basis", max_length=40)
    required: bool = True
    priority: int = 0


class KnowledgeSourceOptionRead(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    source_type: str
    content_type: str
    status: str
    health: str
    parser_status: str | None = None
    index_status: str | None = None
    checksum: str | None = None
    version: str | None = None
    last_indexed_at: str | None = None
    error_message: str | None = None
    bound_agent_ids: list[UUID] = Field(default_factory=list)
    blocker: bool = False
    blocker_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentKnowledgeBindingRead(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    knowledge_source_id: UUID
    source_name: str
    source_type: str
    status: str
    health: str
    required: bool
    binding_mode: str
    priority: int
    blocker: bool
    blocker_reason: str | None = None
    checksum: str | None = None
    version: str | None = None
    last_indexed_at: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityOptionRead(BaseModel):
    key: str
    label: str
    kind: str
    category: str
    description: str
    risk_level: str
    side_effect_type: str
    has_side_effects: bool
    default_mode: str
    required_auth: bool
    required_permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    publish_blockers: list[str] = Field(default_factory=list)


class AgentToolBindingRead(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    tool_name: str
    label: str
    category: str
    enabled: bool
    required: bool
    risk_level: str
    side_effect_type: str
    has_side_effects: bool
    blocker: bool
    blocker_reason: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentActionBindingRead(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    action_key: str
    label: str
    category: str
    enabled: bool
    execution_mode: str
    approval_required: bool
    risk_level: str
    side_effect_type: str
    has_side_effects: bool
    required_auth: bool
    required_permissions: list[str] = Field(default_factory=list)
    permissions: dict[str, Any] = Field(default_factory=dict)
    blocker: bool
    blocker_reason: str | None = None
    publish_blockers: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuilderOption(BaseModel):
    id: str
    label: str
    type: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuilderOptionsRead(BaseModel):
    knowledge_sources: list[BuilderOption] = Field(default_factory=list)
    tools: list[BuilderOption] = Field(default_factory=list)
    actions: list[BuilderOption] = Field(default_factory=list)
    workflows: list[BuilderOption] = Field(default_factory=list)
    registry_status: dict[str, str] = Field(default_factory=dict)


class AgentBuilderStateRead(BaseModel):
    agent: ProductAgentRead
    versions: list[AgentVersionRead] = Field(default_factory=list)
    deployments: list[AgentDeploymentRead] = Field(default_factory=list)
    draft_version: AgentVersionRead | None = None
    published_version: AgentVersionRead | None = None


class AgentBuilderConfigUpdate(AgentVersionUpdate):
    pass


class AgentBuilderReadinessCheck(BaseModel):
    code: str
    label: str
    status: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBuilderReadinessRead(BaseModel):
    status: str
    version_id: UUID
    agent_id: UUID | None = None
    checks: list[AgentBuilderReadinessCheck]
    blocking_codes: list[str] = Field(default_factory=list)
    safety: dict[str, bool] = Field(default_factory=dict)
    test_lab_passed: bool = False
    live_publish_allowed: bool = False


class AgentTestSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    mode: str = Field(default="draft_validation", max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTestSuiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_version_id: UUID
    name: str
    mode: str
    status: str
    last_run_id: UUID | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AgentTestScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTestScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    test_suite_id: UUID
    name: str
    turns: list[Any]
    expected: dict[str, Any]
    status: str
    metadata_json: dict[str, Any]
    created_at: datetime


class AgentTestRunCreate(BaseModel):
    mode: str = Field(default="no_send", max_length=40)
    execution_mode: str = Field(default="simulated_contract", max_length=40)
    review_required: bool = True


class AgentTestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_version_id: UUID
    test_suite_id: UUID
    mode: str
    status: str
    decision: str
    scenario_results: list[Any]
    turn_results: list[Any]
    pass_count: int
    fail_count: int
    blocked_count: int
    trace_ids: list[Any]
    outbox_audit_result: dict[str, Any]
    side_effect_audit_result: dict[str, Any]
    coverage_summary: dict[str, Any]
    review_required: bool
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

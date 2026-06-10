from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from atendia.db.base import Base


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "version_number",
            name="uq_agent_versions_tenant_agent_number",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_agent_versions_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", server_default="draft")
    is_immutable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    role: Mapped[str | None] = mapped_column(String(80))
    tone: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(20))
    instructions: Mapped[str | None] = mapped_column(Text)
    prompt_blocks: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    knowledge_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    tool_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    action_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    field_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    workflow_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    safety_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    test_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID | None] = mapped_column()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentDeployment(Base):
    __tablename__ = "agent_deployments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "channel",
            "environment",
            name="uq_agent_deployments_scope",
        ),
        CheckConstraint(
            "publish_state IN ("
            "'draft', 'test_required', 'test_passed', 'ready_for_approval', "
            "'published_no_send', 'paused', 'rollback_required', 'rolled_back', 'archived'"
            ")",
            name="ck_agent_deployments_publish_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    active_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL"), index=True
    )
    rollback_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), default="test_lab", server_default="test_lab")
    environment: Mapped[str] = mapped_column(
        String(40), default="no_send", server_default="no_send"
    )
    publish_state: Mapped[str] = mapped_column(String(40), default="draft", server_default="draft")
    runtime_mode: Mapped[str] = mapped_column(
        String(80), default="no_send", server_default="no_send"
    )
    send_scope: Mapped[str] = mapped_column(String(80), default="none", server_default="none")
    send_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    outbox_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    live_send_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    single_contact_smoke_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    actions_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    workflow_events_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    workflow_side_effects_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    canary_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    open_production_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by_user_id: Mapped[UUID | None] = mapped_column()
    approved_by_user_id: Mapped[UUID | None] = mapped_column()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentKnowledgeSourceBinding(Base):
    __tablename__ = "agent_knowledge_source_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "knowledge_source_id",
            name="uq_agent_knowledge_source_bindings_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    knowledge_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"), index=True
    )
    binding_mode: Mapped[str] = mapped_column(String(40), default="read", server_default="read")
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentToolBinding(Base):
    __tablename__ = "agent_tool_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "tool_name",
            name="uq_agent_tool_bindings_tool",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    timeout_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentActionBinding(Base):
    __tablename__ = "agent_action_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "action_key",
            name="uq_agent_action_bindings_action",
        ),
        CheckConstraint(
            "execution_mode IN ('disabled', 'dry_run_only', 'approval_required')",
            name="ck_agent_action_bindings_execution_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    action_key: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    execution_mode: Mapped[str] = mapped_column(
        String(40), default="disabled", server_default="disabled"
    )
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    input_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    output_schema: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentFieldPermission(Base):
    __tablename__ = "agent_field_permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "field_key",
            name="uq_agent_field_permissions_field",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    field_key: Mapped[str] = mapped_column(String(160), nullable=False)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    can_write: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    write_policy: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentWorkflowBinding(Base):
    __tablename__ = "agent_workflow_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_version_id",
            "workflow_id",
            "event_type",
            name="uq_agent_workflow_bindings_workflow_event",
        ),
        CheckConstraint(
            "execution_mode IN ('disabled', 'dry_run_only', 'approval_required')",
            name="ck_agent_workflow_bindings_execution_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    execution_mode: Mapped[str] = mapped_column(
        String(40), default="disabled", server_default="disabled"
    )
    side_effects_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    customer_visible_output_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTestSuite(Base):
    __tablename__ = "agent_test_suites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), default="no_send", server_default="no_send")
    status: Mapped[str] = mapped_column(String(40), default="draft", server_default="draft")
    last_run_id: Mapped[UUID | None] = mapped_column()
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentTestScenario(Base):
    __tablename__ = "agent_test_scenarios"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    test_suite_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_test_suites.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    turns: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    expected: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(40), default="draft", server_default="draft")
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTestRun(Base):
    __tablename__ = "agent_test_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('no_send', 'parity_check')",
            name="ck_agent_test_runs_mode",
        ),
        CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'blocked')",
            name="ck_agent_test_runs_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    test_suite_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_test_suites.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(40), default="no_send", server_default="no_send")
    status: Mapped[str] = mapped_column(String(40), default="running", server_default="running")
    decision: Mapped[str] = mapped_column(String(80), default="TEST_LAB_FAILED")
    scenario_results: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    turn_results: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    pass_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fail_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    trace_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    outbox_audit_result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    side_effect_audit_result: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    coverage_summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_user_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentPublishRequest(Base):
    __tablename__ = "agent_publish_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'draft', 'blocked', 'ready_for_approval', 'approved_no_send', 'rejected'"
            ")",
            name="ck_agent_publish_requests_status",
        ),
        CheckConstraint(
            "requested_state IN ('published_no_send')",
            name="ck_agent_publish_requests_requested_state",
        ),
        CheckConstraint(
            "send_scope IN ('none', 'test_lab_no_send')",
            name="ck_agent_publish_requests_send_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), index=True
    )
    deployment_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_deployments.id", ondelete="CASCADE"), index=True
    )
    requested_state: Mapped[str] = mapped_column(
        String(40), default="published_no_send", server_default="published_no_send"
    )
    status: Mapped[str] = mapped_column(String(40), default="draft", server_default="draft")
    send_scope: Mapped[str] = mapped_column(String(80), default="none", server_default="none")
    channel_scope: Mapped[str | None] = mapped_column(String(80))
    audience_scope: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    test_run_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    readiness_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    blockers: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    rollback_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    approval_text: Mapped[str | None] = mapped_column(Text)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    requested_by_user_id: Mapped[UUID | None] = mapped_column()
    approved_by_user_id: Mapped[UUID | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentPublishEvent(Base):
    __tablename__ = "agent_publish_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    deployment_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_deployments.id", ondelete="CASCADE"), index=True
    )
    agent_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    from_state: Mapped[str | None] = mapped_column(String(40))
    to_state: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[UUID | None] = mapped_column()
    safety_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

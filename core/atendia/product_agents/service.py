from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import (
    AgentActionBinding,
    AgentDeployment,
    AgentFieldPermission,
    AgentKnowledgeSourceBinding,
    AgentPublishEvent,
    AgentPublishRequest,
    AgentTestRun,
    AgentTestScenario,
    AgentTestSuite,
    AgentToolBinding,
    AgentVersion,
    AgentWorkflowBinding,
)
from atendia.db.models.workflow import Workflow
from atendia.product_agents.capability_registry import (
    CapabilityKind,
    ProductCapability,
    get_capability,
    list_capabilities,
)

VERSION_STATUS_DRAFT = "draft"
VERSION_STATUS_PUBLISHED = "published"
VERSION_STATUS_ARCHIVED = "archived"

DEPLOYMENT_STATE_DRAFT = "draft"
DEPLOYMENT_STATE_TEST_REQUIRED = "test_required"
DEPLOYMENT_STATE_TEST_PASSED = "test_passed"
DEPLOYMENT_STATE_READY_FOR_APPROVAL = "ready_for_approval"
DEPLOYMENT_STATE_PUBLISHED_NO_SEND = "published_no_send"
DEPLOYMENT_STATE_PAUSED = "paused"
DEPLOYMENT_STATE_ROLLBACK_REQUIRED = "rollback_required"
DEPLOYMENT_STATE_ROLLED_BACK = "rolled_back"
DEPLOYMENT_STATE_ARCHIVED = "archived"

ALLOWED_DEPLOYMENT_STATES = {
    DEPLOYMENT_STATE_DRAFT,
    DEPLOYMENT_STATE_TEST_REQUIRED,
    DEPLOYMENT_STATE_TEST_PASSED,
    DEPLOYMENT_STATE_READY_FOR_APPROVAL,
    DEPLOYMENT_STATE_PUBLISHED_NO_SEND,
    DEPLOYMENT_STATE_PAUSED,
    DEPLOYMENT_STATE_ROLLBACK_REQUIRED,
    DEPLOYMENT_STATE_ROLLED_BACK,
    DEPLOYMENT_STATE_ARCHIVED,
}

ALLOWED_DEPLOYMENT_TRANSITIONS = {
    DEPLOYMENT_STATE_DRAFT: {
        DEPLOYMENT_STATE_TEST_REQUIRED,
        DEPLOYMENT_STATE_PAUSED,
        DEPLOYMENT_STATE_ARCHIVED,
    },
    DEPLOYMENT_STATE_TEST_REQUIRED: {
        DEPLOYMENT_STATE_TEST_PASSED,
        DEPLOYMENT_STATE_PAUSED,
    },
    DEPLOYMENT_STATE_TEST_PASSED: {
        DEPLOYMENT_STATE_READY_FOR_APPROVAL,
        DEPLOYMENT_STATE_PAUSED,
    },
    DEPLOYMENT_STATE_READY_FOR_APPROVAL: {
        DEPLOYMENT_STATE_PUBLISHED_NO_SEND,
        DEPLOYMENT_STATE_PAUSED,
    },
    DEPLOYMENT_STATE_PUBLISHED_NO_SEND: {
        DEPLOYMENT_STATE_PAUSED,
        DEPLOYMENT_STATE_ROLLBACK_REQUIRED,
    },
    DEPLOYMENT_STATE_PAUSED: {
        DEPLOYMENT_STATE_TEST_REQUIRED,
        DEPLOYMENT_STATE_PUBLISHED_NO_SEND,
        DEPLOYMENT_STATE_ARCHIVED,
    },
    DEPLOYMENT_STATE_ROLLBACK_REQUIRED: {
        DEPLOYMENT_STATE_ROLLED_BACK,
        DEPLOYMENT_STATE_PAUSED,
    },
    DEPLOYMENT_STATE_ROLLED_BACK: {
        DEPLOYMENT_STATE_PUBLISHED_NO_SEND,
        DEPLOYMENT_STATE_PAUSED,
    },
    DEPLOYMENT_STATE_ARCHIVED: set(),
}

BLOCKED_LIVE_STATES = {
    "published_live_limited",
    "single_contact_smoke",
    "canary",
    "production",
    "open_production",
}

SAFE_DEPLOYMENT_FLAGS = {
    "send_enabled",
    "outbox_enabled",
    "live_send_enabled",
    "single_contact_smoke_enabled",
    "actions_enabled",
    "workflow_events_enabled",
    "workflow_side_effects_enabled",
    "canary_enabled",
    "open_production_enabled",
}

SAFE_ACTION_MODES = {"disabled", "dry_run_only", "approval_required"}
BLOCKED_ACTION_LIVE_MODES = {"live", "live_limited", "production"}
TEST_SUITE_MODES = {
    "draft_validation",
    "publish_readiness",
    "regression",
    "incident_replay",
    "parity_check",
}
TEST_RUN_MODES = {"no_send", "parity_check"}

PUBLISH_REQUEST_STATUS_DRAFT = "draft"
PUBLISH_REQUEST_STATUS_BLOCKED = "blocked"
PUBLISH_REQUEST_STATUS_READY = "ready_for_approval"
PUBLISH_REQUEST_STATUS_APPROVED_NO_SEND = "approved_no_send"
PUBLISH_REQUEST_STATUS_REJECTED = "rejected"
PUBLISH_REQUEST_STATUSES = {
    PUBLISH_REQUEST_STATUS_DRAFT,
    PUBLISH_REQUEST_STATUS_BLOCKED,
    PUBLISH_REQUEST_STATUS_READY,
    PUBLISH_REQUEST_STATUS_APPROVED_NO_SEND,
    PUBLISH_REQUEST_STATUS_REJECTED,
}
PUBLISH_REQUEST_STATES = {DEPLOYMENT_STATE_PUBLISHED_NO_SEND}
PUBLISH_REQUEST_SEND_SCOPES = {"none", "test_lab_no_send"}

SOURCE_HEALTHY_STATUSES = {"active", "indexed", "ready"}
SOURCE_UNHEALTHY_STATUSES = {"missing", "failed", "unhealthy", "deleted", "disabled", "stale"}
SOURCE_PENDING_STATUSES = {"draft", "uploaded", "parsing", "partially_processed"}
SOURCE_HEALTH_BLOCKERS = {
    "missing": "source_missing",
    "failed": "source_unhealthy",
    "unhealthy": "source_unhealthy",
    "deleted": "source_deleted",
    "disabled": "source_disabled",
    "stale": "source_stale",
    "draft": "source_not_indexed",
    "uploaded": "source_not_indexed",
    "parsing": "source_not_indexed",
    "partially_processed": "source_not_indexed",
}


class ProductAgentError(ValueError):
    """Base exception for Product-First agent control-plane validation."""


class ProductAgentNotFoundError(ProductAgentError):
    """Raised when a tenant-scoped entity does not exist."""


class ImmutableAgentVersionError(ProductAgentError):
    """Raised when a published agent version would be modified."""


class PublishStateTransitionError(ProductAgentError):
    """Raised when a deployment state transition is unsafe or invalid."""


class TestLabValidationError(ProductAgentError):
    """Raised when a Product-First Test Lab suite or scenario is invalid."""


def ensure_version_mutable(version: AgentVersion) -> None:
    if version.is_immutable or version.status == VERSION_STATUS_PUBLISHED:
        raise ImmutableAgentVersionError("published agent versions are immutable")


def mark_version_published(
    version: AgentVersion,
    *,
    now: datetime | None = None,
) -> AgentVersion:
    ensure_version_mutable(version)
    version.status = VERSION_STATUS_PUBLISHED
    version.is_immutable = True
    version.published_at = now or datetime.now(UTC)
    return version


def validate_json_schema_object(schema: dict[str, Any], *, label: str) -> None:
    if not isinstance(schema, dict):
        raise ProductAgentError(f"{label} must be a JSON object")
    schema_type = schema.get("type")
    if schema_type is not None and schema_type != "object":
        raise ProductAgentError(f"{label} must describe a JSON object")
    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise ProductAgentError(f"{label}.properties must be a JSON object")


def validate_tool_binding_schema(
    *,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> None:
    validate_json_schema_object(input_schema, label="input_schema")
    validate_json_schema_object(output_schema, label="output_schema")


def validate_action_permissions(
    *,
    execution_mode: str,
    permissions: dict[str, Any],
    enabled: bool,
) -> None:
    if execution_mode not in SAFE_ACTION_MODES:
        raise ProductAgentError("execution_mode is not allowed for Product-First action binding")
    if not isinstance(permissions, dict):
        raise ProductAgentError("permissions must be a JSON object")
    if enabled and execution_mode == "disabled":
        raise ProductAgentError("enabled actions must not use disabled execution_mode")
    if execution_mode != "disabled" and not permissions:
        raise ProductAgentError("non-disabled actions require explicit permissions")


def validate_publish_state_transition(from_state: str, to_state: str) -> None:
    if to_state in BLOCKED_LIVE_STATES:
        raise PublishStateTransitionError(
            "live publish states are blocked in Product Entities phase"
        )
    if to_state not in ALLOWED_DEPLOYMENT_STATES:
        raise PublishStateTransitionError("unknown Product-First publish state")
    allowed = ALLOWED_DEPLOYMENT_TRANSITIONS.get(from_state, set())
    if to_state not in allowed and to_state != from_state:
        raise PublishStateTransitionError(
            f"invalid publish state transition: {from_state} -> {to_state}"
        )


def ensure_deployment_send_safety(deployment: AgentDeployment) -> None:
    enabled_flags = [
        flag_name
        for flag_name in SAFE_DEPLOYMENT_FLAGS
        if bool(getattr(deployment, flag_name, False))
    ]
    if enabled_flags:
        raise PublishStateTransitionError(
            f"Product Entities phase cannot enable live side effects: {', '.join(enabled_flags)}"
        )


def apply_deployment_state_transition(
    deployment: AgentDeployment,
    *,
    to_state: str,
    now: datetime | None = None,
) -> AgentDeployment:
    validate_publish_state_transition(deployment.publish_state, to_state)
    ensure_deployment_send_safety(deployment)
    deployment.publish_state = to_state
    if to_state == DEPLOYMENT_STATE_PUBLISHED_NO_SEND:
        deployment.runtime_mode = "no_send"
        deployment.send_scope = "none"
        for flag_name in SAFE_DEPLOYMENT_FLAGS:
            setattr(deployment, flag_name, False)
        deployment.published_at = now or datetime.now(UTC)
    ensure_deployment_send_safety(deployment)
    return deployment


async def get_agent_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> Agent:
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ProductAgentNotFoundError("agent not found for tenant")
    return agent


async def create_product_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    role: str,
    tone: str | None,
    language: str | None,
    instructions: str | None,
) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        name=name,
        role=role,
        status="draft",
        behavior_mode="strict",
        tone=tone,
        language=language,
        system_prompt=instructions,
        ops_config={"product_first": True},
    )
    session.add(agent)
    await session.flush()
    return agent


async def list_product_agents(session: AsyncSession, *, tenant_id: UUID) -> list[Agent]:
    result = await session.execute(select(Agent).where(Agent.tenant_id == tenant_id))
    return list(result.scalars().all())


async def list_builder_options(session: AsyncSession, *, tenant_id: UUID) -> dict[str, Any]:
    source_options = await list_knowledge_source_options(session, tenant_id=tenant_id)
    workflow_result = await session.execute(
        select(Workflow).where(Workflow.tenant_id == tenant_id).order_by(Workflow.name)
    )
    knowledge_sources = [
        {
            "id": str(source["id"]),
            "label": source["name"],
            "type": source["source_type"],
            "status": source["status"],
            "metadata": {
                "content_type": source["content_type"],
                "health": source["health"],
                "blocker": source["blocker"],
                "blocker_reason": source["blocker_reason"],
            },
        }
        for source in source_options
    ]
    workflows = [
        {
            "id": str(workflow.id),
            "label": workflow.name,
            "type": workflow.trigger_type,
            "status": "active" if workflow.active else "inactive",
            "metadata": {
                "version": workflow.version,
                "side_effects_default": False,
            },
        }
        for workflow in workflow_result.scalars().all()
    ]
    return {
        "knowledge_sources": knowledge_sources,
        "tools": [
            {
                "id": capability["key"],
                "label": capability["label"],
                "type": capability["category"],
                "status": "available",
                "metadata": capability,
            }
            for capability in await list_tool_options(session, tenant_id=tenant_id)
        ],
        "actions": [
            {
                "id": capability["key"],
                "label": capability["label"],
                "type": capability["category"],
                "status": capability["default_mode"],
                "metadata": capability,
            }
            for capability in await list_action_options(session, tenant_id=tenant_id)
        ],
        "workflows": workflows,
        "registry_status": {
            "tools": "connected",
            "actions": "connected_no_live",
            "send": "blocked_for_builder_mvp",
        },
    }


async def list_knowledge_source_options(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    source_result = await session.execute(
        select(KnowledgeSource)
        .where(KnowledgeSource.tenant_id == tenant_id)
        .order_by(KnowledgeSource.name)
    )
    binding_result = await session.execute(
        select(AgentKnowledgeSourceBinding.knowledge_source_id, AgentVersion.agent_id)
        .join(AgentVersion, AgentVersion.id == AgentKnowledgeSourceBinding.agent_version_id)
        .where(
            AgentKnowledgeSourceBinding.tenant_id == tenant_id,
            AgentVersion.tenant_id == tenant_id,
        )
    )
    bound_agents_by_source: dict[UUID, set[UUID]] = {}
    for source_id, agent_id in binding_result.all():
        bound_agents_by_source.setdefault(source_id, set()).add(agent_id)
    return [
        _source_option(source, sorted(bound_agents_by_source.get(source.id, set())))
        for source in source_result.scalars().all()
    ]


async def get_agent_builder_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> dict[str, Any]:
    agent = await get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    versions_result = await session.execute(
        select(AgentVersion)
        .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
    )
    deployments_result = await session.execute(
        select(AgentDeployment)
        .where(AgentDeployment.tenant_id == tenant_id, AgentDeployment.agent_id == agent_id)
        .order_by(AgentDeployment.created_at.desc())
    )
    versions = list(versions_result.scalars().all())
    deployments = list(deployments_result.scalars().all())
    draft_version = next(
        (version for version in versions if version.status == VERSION_STATUS_DRAFT),
        None,
    )
    published_version = next(
        (version for version in versions if version.status == VERSION_STATUS_PUBLISHED),
        None,
    )
    return {
        "agent": agent,
        "versions": versions,
        "deployments": deployments,
        "draft_version": draft_version,
        "published_version": published_version,
    }


async def create_builder_draft_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    payload: dict[str, Any],
    created_by_user_id: UUID | None,
) -> AgentVersion:
    agent = await get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    draft_payload = {
        "role": payload.get("role", agent.role),
        "tone": payload.get("tone", agent.tone),
        "language": payload.get("language", agent.language),
        "instructions": payload.get("instructions", agent.system_prompt),
        "prompt_blocks": payload.get("prompt_blocks") or [],
        "knowledge_policy": payload.get("knowledge_policy") or {},
        "tool_policy": payload.get("tool_policy") or {},
        "action_policy": payload.get("action_policy") or {},
        "field_policy": payload.get("field_policy") or {},
        "workflow_policy": payload.get("workflow_policy") or {},
        "safety_policy": payload.get("safety_policy") or {},
        "test_policy": payload.get("test_policy") or {},
        "snapshot": payload.get("snapshot") or {"builder_source": "product_first_builder"},
        "change_summary": payload.get("change_summary") or "Builder draft",
    }
    return await create_agent_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        payload=draft_payload,
        created_by_user_id=created_by_user_id,
    )


async def update_product_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    values: dict[str, Any],
) -> Agent:
    agent = await get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    for field_name in ("name", "role", "tone", "language"):
        if field_name in values:
            setattr(agent, field_name, values[field_name])
    if "instructions" in values:
        agent.system_prompt = values["instructions"]
    await session.flush()
    return agent


async def create_agent_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    payload: dict[str, Any],
    created_by_user_id: UUID | None,
) -> AgentVersion:
    await get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    result = await session.execute(
        select(func.max(AgentVersion.version_number)).where(
            AgentVersion.tenant_id == tenant_id,
            AgentVersion.agent_id == agent_id,
        )
    )
    next_version = (result.scalar_one_or_none() or 0) + 1
    version = AgentVersion(
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=next_version,
        role=payload.get("role"),
        tone=payload.get("tone"),
        language=payload.get("language"),
        instructions=payload.get("instructions"),
        prompt_blocks=payload.get("prompt_blocks") or [],
        knowledge_policy=payload.get("knowledge_policy") or {},
        tool_policy=payload.get("tool_policy") or {},
        action_policy=payload.get("action_policy") or {},
        field_policy=payload.get("field_policy") or {},
        workflow_policy=payload.get("workflow_policy") or {},
        safety_policy=payload.get("safety_policy") or {},
        test_policy=payload.get("test_policy") or {},
        snapshot=payload.get("snapshot") or {},
        change_summary=payload.get("change_summary"),
        created_by_user_id=created_by_user_id,
    )
    session.add(version)
    await session.flush()
    return version


async def get_agent_version_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> AgentVersion:
    result = await session.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.tenant_id == tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise ProductAgentNotFoundError("agent version not found for tenant")
    return version


async def update_agent_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
    values: dict[str, Any],
) -> AgentVersion:
    version = await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    ensure_version_mutable(version)
    for field_name, value in values.items():
        if hasattr(version, field_name):
            setattr(version, field_name, value)
    await session.flush()
    return version


async def publish_agent_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> AgentVersion:
    version = await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    mark_version_published(version)
    await session.flush()
    return version


async def create_agent_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str,
    channel: str,
    environment: str,
    active_version_id: UUID | None,
    created_by_user_id: UUID | None,
) -> AgentDeployment:
    await get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    if active_version_id is not None:
        version = await get_agent_version_for_tenant(
            session,
            tenant_id=tenant_id,
            version_id=active_version_id,
        )
        if version.agent_id != agent_id:
            raise ProductAgentError("active_version_id does not belong to agent")
    deployment = AgentDeployment(
        tenant_id=tenant_id,
        agent_id=agent_id,
        active_version_id=active_version_id,
        name=name,
        channel=channel,
        environment=environment,
        created_by_user_id=created_by_user_id,
    )
    ensure_deployment_send_safety(deployment)
    session.add(deployment)
    await session.flush()
    return deployment


async def get_deployment_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
) -> AgentDeployment:
    result = await session.execute(
        select(AgentDeployment).where(
            AgentDeployment.id == deployment_id,
            AgentDeployment.tenant_id == tenant_id,
        )
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise ProductAgentNotFoundError("agent deployment not found for tenant")
    return deployment


async def transition_agent_deployment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
    to_state: str,
    actor_user_id: UUID | None,
    reason: str | None,
) -> AgentDeployment:
    deployment = await get_deployment_for_tenant(
        session,
        tenant_id=tenant_id,
        deployment_id=deployment_id,
    )
    from_state = deployment.publish_state
    apply_deployment_state_transition(deployment, to_state=to_state)
    session.add(
        AgentPublishEvent(
            tenant_id=tenant_id,
            deployment_id=deployment.id,
            agent_version_id=deployment.active_version_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor_user_id=actor_user_id,
            safety_snapshot={flag_name: False for flag_name in SAFE_DEPLOYMENT_FLAGS},
        )
    )
    await session.flush()
    return deployment


def validate_publish_request_payload(
    *,
    requested_state: str,
    send_scope: str,
    audience_scope: dict[str, Any],
) -> None:
    if requested_state in BLOCKED_LIVE_STATES or requested_state not in PUBLISH_REQUEST_STATES:
        raise PublishStateTransitionError("Publish Control MVP only allows published_no_send")
    if send_scope not in PUBLISH_REQUEST_SEND_SCOPES:
        raise PublishStateTransitionError("Publish Control MVP cannot enable live send scope")
    if not isinstance(audience_scope, dict):
        raise ProductAgentError("audience_scope must be a JSON object")


async def create_publish_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
    agent_version_id: UUID,
    requested_state: str,
    send_scope: str,
    channel_scope: str | None,
    audience_scope: dict[str, Any],
    rollback_version_id: UUID | None,
    approval_text: str | None,
    requested_by_user_id: UUID | None,
) -> AgentPublishRequest:
    validate_publish_request_payload(
        requested_state=requested_state,
        send_scope=send_scope,
        audience_scope=audience_scope,
    )
    deployment = await get_deployment_for_tenant(
        session,
        tenant_id=tenant_id,
        deployment_id=deployment_id,
    )
    version = await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=agent_version_id,
    )
    if version.agent_id != deployment.agent_id:
        raise ProductAgentError("agent_version_id does not belong to deployment agent")
    if rollback_version_id is not None:
        rollback_version = await get_agent_version_for_tenant(
            session,
            tenant_id=tenant_id,
            version_id=rollback_version_id,
        )
        if rollback_version.agent_id != deployment.agent_id:
            raise ProductAgentError("rollback_version_id does not belong to deployment agent")
    publish_request = AgentPublishRequest(
        tenant_id=tenant_id,
        agent_id=deployment.agent_id,
        agent_version_id=version.id,
        deployment_id=deployment.id,
        requested_state=requested_state,
        send_scope=send_scope,
        channel_scope=channel_scope,
        audience_scope=audience_scope,
        rollback_version_id=rollback_version_id,
        approval_text=approval_text,
        requested_by_user_id=requested_by_user_id,
    )
    session.add(publish_request)
    await session.flush()
    await evaluate_publish_request(session, tenant_id=tenant_id, request_id=publish_request.id)
    return publish_request


async def get_publish_request_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
) -> AgentPublishRequest:
    result = await session.execute(
        select(AgentPublishRequest).where(
            AgentPublishRequest.id == request_id,
            AgentPublishRequest.tenant_id == tenant_id,
        )
    )
    publish_request = result.scalar_one_or_none()
    if publish_request is None:
        raise ProductAgentNotFoundError("publish request not found for tenant")
    return publish_request


async def get_latest_publish_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
) -> AgentPublishRequest | None:
    await get_deployment_for_tenant(session, tenant_id=tenant_id, deployment_id=deployment_id)
    result = await session.execute(
        select(AgentPublishRequest)
        .where(
            AgentPublishRequest.tenant_id == tenant_id,
            AgentPublishRequest.deployment_id == deployment_id,
        )
        .order_by(AgentPublishRequest.created_at.desc())
    )
    return result.scalar_one_or_none()


async def evaluate_publish_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
) -> AgentPublishRequest:
    publish_request = await get_publish_request_for_tenant(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    deployment = await get_deployment_for_tenant(
        session,
        tenant_id=tenant_id,
        deployment_id=publish_request.deployment_id,
    )
    version = await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=publish_request.agent_version_id,
    )
    readiness = await evaluate_builder_readiness(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
    )
    latest_run = await _latest_test_run_for_version(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
    )
    blockers = _publish_request_blockers(
        publish_request=publish_request,
        deployment=deployment,
        version=version,
        readiness=readiness,
        latest_run=latest_run,
    )
    # Respond-Style gates (Phase 13A): additive blockers for deployments
    # that opted into the direct route. Never removes existing blockers.
    from atendia.product_agents.publish_gates import respond_style_publish_blockers

    blockers.extend(
        await respond_style_publish_blockers(
            session,
            tenant_id=tenant_id,
            version_id=version.id,
            deployment=deployment,
        )
    )
    publish_request.blockers = blockers
    publish_request.test_run_ids = [str(latest_run.id)] if latest_run is not None else []
    publish_request.readiness_snapshot = {
        "builder_readiness": readiness,
        "latest_test_run": _test_run_snapshot(latest_run),
        "deployment": {
            "id": str(deployment.id),
            "publish_state": deployment.publish_state,
            "runtime_mode": deployment.runtime_mode,
            "send_scope": deployment.send_scope,
            "safety": {
                flag_name: bool(getattr(deployment, flag_name, False))
                for flag_name in SAFE_DEPLOYMENT_FLAGS
            },
        },
    }
    publish_request.status = (
        PUBLISH_REQUEST_STATUS_BLOCKED if blockers else PUBLISH_REQUEST_STATUS_READY
    )
    publish_request.decision_reason = "blocked" if blockers else "ready_for_no_send_approval"
    await session.flush()
    return publish_request


async def approve_publish_request_no_send(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
    approved_by_user_id: UUID | None,
    approval_text: str | None,
) -> AgentPublishRequest:
    publish_request = await evaluate_publish_request(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    if publish_request.blockers:
        raise PublishStateTransitionError("publish request has blocking gates")
    deployment = await get_deployment_for_tenant(
        session,
        tenant_id=tenant_id,
        deployment_id=publish_request.deployment_id,
    )
    from_state = deployment.publish_state
    deployment.active_version_id = publish_request.agent_version_id
    deployment.rollback_version_id = publish_request.rollback_version_id
    _advance_deployment_to_ready_for_no_send(deployment)
    apply_deployment_state_transition(
        deployment,
        to_state=DEPLOYMENT_STATE_PUBLISHED_NO_SEND,
    )
    ensure_deployment_send_safety(deployment)
    publish_request.status = PUBLISH_REQUEST_STATUS_APPROVED_NO_SEND
    publish_request.approved_by_user_id = approved_by_user_id
    publish_request.approval_text = approval_text or publish_request.approval_text
    publish_request.decision_reason = "approved_no_send"
    publish_request.decided_at = datetime.now(UTC)
    session.add(
        AgentPublishEvent(
            tenant_id=tenant_id,
            deployment_id=deployment.id,
            agent_version_id=deployment.active_version_id,
            from_state=from_state,
            to_state=deployment.publish_state,
            reason="publish_control_approved_no_send",
            actor_user_id=approved_by_user_id,
            safety_snapshot={
                "publish_request_id": str(publish_request.id),
                **{flag_name: False for flag_name in SAFE_DEPLOYMENT_FLAGS},
            },
        )
    )
    await session.flush()
    return publish_request


async def reject_publish_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
    actor_user_id: UUID | None,
    reason: str | None,
) -> AgentPublishRequest:
    publish_request = await get_publish_request_for_tenant(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    publish_request.status = PUBLISH_REQUEST_STATUS_REJECTED
    publish_request.decision_reason = reason or "rejected"
    publish_request.approved_by_user_id = actor_user_id
    publish_request.decided_at = datetime.now(UTC)
    await session.flush()
    return publish_request


async def create_tool_binding(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_version_id: UUID,
    tool_name: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    required: bool,
) -> AgentToolBinding:
    await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=agent_version_id,
    )
    validate_tool_binding_schema(input_schema=input_schema, output_schema=output_schema)
    binding = AgentToolBinding(
        tenant_id=tenant_id,
        agent_version_id=agent_version_id,
        tool_name=tool_name,
        input_schema=input_schema,
        output_schema=output_schema,
        required=required,
    )
    session.add(binding)
    await session.flush()
    return binding


async def create_action_binding(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_version_id: UUID,
    action_key: str,
    execution_mode: str,
    permissions: dict[str, Any],
    enabled: bool,
) -> AgentActionBinding:
    await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=agent_version_id,
    )
    validate_action_permissions(
        execution_mode=execution_mode,
        permissions=permissions,
        enabled=enabled,
    )
    binding = AgentActionBinding(
        tenant_id=tenant_id,
        agent_version_id=agent_version_id,
        action_key=action_key,
        execution_mode=execution_mode,
        permissions=permissions,
        enabled=enabled,
    )
    session.add(binding)
    await session.flush()
    return binding


async def list_tool_options(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    await _assert_tenant_id_shape(tenant_id)
    return [_capability_option(capability) for capability in list_capabilities("tool")]


async def list_action_options(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    await _assert_tenant_id_shape(tenant_id)
    return [_capability_option(capability) for capability in list_capabilities("action")]


async def list_agent_tool_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> list[dict[str, Any]]:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    result = await session.execute(
        select(AgentToolBinding).where(
            AgentToolBinding.tenant_id == tenant_id,
            AgentToolBinding.agent_version_id == version.id,
        )
    )
    return [
        _tool_binding_read(binding, agent_id=agent_id)
        for binding in result.scalars().all()
    ]


async def bind_agent_tool(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    tool_name: str,
    enabled: bool,
    required: bool,
) -> dict[str, Any]:
    capability = _require_capability(tool_name, kind="tool")
    if capability.has_side_effects:
        raise ProductAgentError("tools must not have side effects")
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    ensure_version_mutable(version)
    binding = AgentToolBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        tool_name=capability.key,
        enabled=enabled,
        required=required,
        input_schema=capability.input_schema,
        output_schema=capability.output_schema,
        metadata_json={
            "product_first_builder": True,
            "capability_kind": "tool",
            "side_effect_type": capability.side_effect_type,
        },
    )
    session.add(binding)
    await session.flush()
    return _tool_binding_read(binding, agent_id=agent_id)


async def unbind_agent_tool(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    binding_id: UUID,
) -> None:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    ensure_version_mutable(version)
    result = await session.execute(
        select(AgentToolBinding).where(
            AgentToolBinding.id == binding_id,
            AgentToolBinding.tenant_id == tenant_id,
            AgentToolBinding.agent_version_id == version.id,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise ProductAgentNotFoundError("tool binding not found for agent draft")
    await session.delete(binding)
    await session.flush()


async def list_agent_action_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> list[dict[str, Any]]:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    result = await session.execute(
        select(AgentActionBinding).where(
            AgentActionBinding.tenant_id == tenant_id,
            AgentActionBinding.agent_version_id == version.id,
        )
    )
    return [
        _action_binding_read(binding, agent_id=agent_id)
        for binding in result.scalars().all()
    ]


async def bind_agent_action(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    action_key: str,
    enabled: bool,
    execution_mode: str,
    permissions: dict[str, Any],
) -> dict[str, Any]:
    capability = _require_capability(action_key, kind="action")
    _validate_action_binding_against_capability(
        capability,
        enabled=enabled,
        execution_mode=execution_mode,
        permissions=permissions,
    )
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    ensure_version_mutable(version)
    binding = AgentActionBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        action_key=capability.key,
        enabled=enabled,
        execution_mode=execution_mode,
        approval_required=capability.has_side_effects or capability.risk_level == "critical",
        permissions=permissions,
        input_schema=capability.input_schema,
        output_schema=capability.output_schema,
        metadata_json={
            "product_first_builder": True,
            "capability_kind": "action",
            "risk_level": capability.risk_level,
            "side_effect_type": capability.side_effect_type,
        },
    )
    session.add(binding)
    await session.flush()
    return _action_binding_read(binding, agent_id=agent_id)


async def unbind_agent_action(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    binding_id: UUID,
) -> None:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    ensure_version_mutable(version)
    result = await session.execute(
        select(AgentActionBinding).where(
            AgentActionBinding.id == binding_id,
            AgentActionBinding.tenant_id == tenant_id,
            AgentActionBinding.agent_version_id == version.id,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise ProductAgentNotFoundError("action binding not found for agent draft")
    await session.delete(binding)
    await session.flush()


async def list_agent_test_suites(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> list[AgentTestSuite]:
    await get_agent_version_for_tenant(session, tenant_id=tenant_id, version_id=version_id)
    result = await session.execute(
        select(AgentTestSuite)
        .where(
            AgentTestSuite.tenant_id == tenant_id,
            AgentTestSuite.agent_version_id == version_id,
        )
        .order_by(AgentTestSuite.created_at.desc())
    )
    return list(result.scalars().all())


async def create_agent_test_suite(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
    name: str,
    mode: str,
    metadata: dict[str, Any],
) -> AgentTestSuite:
    await get_agent_version_for_tenant(session, tenant_id=tenant_id, version_id=version_id)
    _validate_test_suite_mode(mode)
    if not isinstance(metadata, dict):
        raise TestLabValidationError("test suite metadata must be a JSON object")
    suite = AgentTestSuite(
        tenant_id=tenant_id,
        agent_version_id=version_id,
        name=name,
        mode=mode,
        status="draft",
        metadata_json=metadata,
    )
    session.add(suite)
    await session.flush()
    return suite


async def get_agent_test_suite_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
) -> AgentTestSuite:
    result = await session.execute(
        select(AgentTestSuite).where(
            AgentTestSuite.id == suite_id,
            AgentTestSuite.tenant_id == tenant_id,
        )
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise ProductAgentNotFoundError("test suite not found for tenant")
    return suite


async def list_agent_test_scenarios(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
) -> list[AgentTestScenario]:
    await get_agent_test_suite_for_tenant(session, tenant_id=tenant_id, suite_id=suite_id)
    result = await session.execute(
        select(AgentTestScenario)
        .where(
            AgentTestScenario.tenant_id == tenant_id,
            AgentTestScenario.test_suite_id == suite_id,
        )
        .order_by(AgentTestScenario.created_at)
    )
    return list(result.scalars().all())


async def create_agent_test_scenario(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    name: str,
    turns: list[dict[str, Any]],
    expected: dict[str, Any],
    metadata: dict[str, Any],
) -> AgentTestScenario:
    await get_agent_test_suite_for_tenant(session, tenant_id=tenant_id, suite_id=suite_id)
    _validate_test_scenario_payload(turns=turns, expected=expected, metadata=metadata)
    scenario = AgentTestScenario(
        tenant_id=tenant_id,
        test_suite_id=suite_id,
        name=name,
        turns=turns,
        expected=expected,
        status="draft",
        metadata_json=metadata,
    )
    session.add(scenario)
    await session.flush()
    return scenario


async def get_latest_agent_test_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
) -> AgentTestRun | None:
    await get_agent_test_suite_for_tenant(session, tenant_id=tenant_id, suite_id=suite_id)
    result = await session.execute(
        select(AgentTestRun)
        .where(
            AgentTestRun.tenant_id == tenant_id,
            AgentTestRun.test_suite_id == suite_id,
        )
        .order_by(AgentTestRun.created_at.desc())
    )
    return result.scalar_one_or_none()


def create_agent_test_run_record(
    *,
    tenant_id: UUID,
    agent_version_id: UUID,
    suite_id: UUID,
    mode: str,
    review_required: bool,
    created_by_user_id: UUID | None,
) -> AgentTestRun:
    if mode not in TEST_RUN_MODES:
        raise TestLabValidationError("test run mode is not allowed")
    return AgentTestRun(
        tenant_id=tenant_id,
        agent_version_id=agent_version_id,
        test_suite_id=suite_id,
        mode=mode,
        status="running",
        decision="TEST_LAB_FAILED",
        scenario_results=[],
        turn_results=[],
        trace_ids=[],
        outbox_audit_result={"status": "not_checked"},
        side_effect_audit_result={"status": "not_checked"},
        coverage_summary={"scope": "product_first_test_lab_mvp"},
        review_required=review_required,
        created_by_user_id=created_by_user_id,
    )


async def create_knowledge_source_binding(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_version_id: UUID,
    knowledge_source_id: UUID,
) -> AgentKnowledgeSourceBinding:
    await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=agent_version_id,
    )
    result = await session.execute(
        select(KnowledgeSource.id).where(
            KnowledgeSource.id == knowledge_source_id,
            KnowledgeSource.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise ProductAgentNotFoundError("knowledge source not found for tenant")
    binding = AgentKnowledgeSourceBinding(
        tenant_id=tenant_id,
        agent_version_id=agent_version_id,
        knowledge_source_id=knowledge_source_id,
    )
    session.add(binding)
    await session.flush()
    return binding


async def list_agent_knowledge_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> list[dict[str, Any]]:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    result = await session.execute(
        select(AgentKnowledgeSourceBinding, KnowledgeSource)
        .join(
            KnowledgeSource,
            KnowledgeSource.id == AgentKnowledgeSourceBinding.knowledge_source_id,
        )
        .where(
            AgentKnowledgeSourceBinding.tenant_id == tenant_id,
            AgentKnowledgeSourceBinding.agent_version_id == version.id,
            KnowledgeSource.tenant_id == tenant_id,
        )
        .order_by(AgentKnowledgeSourceBinding.priority.desc(), KnowledgeSource.name)
    )
    return [
        _knowledge_binding_read(binding, source, agent_id=agent_id)
        for binding, source in result.all()
    ]


async def bind_agent_knowledge_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    knowledge_source_id: UUID,
    binding_mode: str,
    required: bool,
    priority: int,
) -> dict[str, Any]:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    ensure_version_mutable(version)
    source = await get_knowledge_source_for_tenant(
        session,
        tenant_id=tenant_id,
        knowledge_source_id=knowledge_source_id,
    )
    health = _source_health(source)
    if source.status.lower() in {"missing", "deleted"}:
        raise ProductAgentError("knowledge source is not bindable")
    binding = AgentKnowledgeSourceBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        knowledge_source_id=knowledge_source_id,
        binding_mode=binding_mode,
        required=required,
        priority=priority,
    )
    binding.metadata_json = {
        "source_health_at_binding": health["health"],
        "source_status_at_binding": health["status"],
        "product_first_builder": True,
    }
    session.add(binding)
    await session.flush()
    return _knowledge_binding_read(binding, source, agent_id=agent_id)


async def unbind_agent_knowledge_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    binding_id: UUID,
) -> None:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    ensure_version_mutable(version)
    result = await session.execute(
        select(AgentKnowledgeSourceBinding).where(
            AgentKnowledgeSourceBinding.id == binding_id,
            AgentKnowledgeSourceBinding.tenant_id == tenant_id,
            AgentKnowledgeSourceBinding.agent_version_id == version.id,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise ProductAgentNotFoundError("knowledge binding not found for agent draft")
    await session.delete(binding)
    await session.flush()


async def get_knowledge_source_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    knowledge_source_id: UUID,
) -> KnowledgeSource:
    result = await session.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.id == knowledge_source_id,
            KnowledgeSource.tenant_id == tenant_id,
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise ProductAgentNotFoundError("knowledge source not found for tenant")
    return source


async def get_draft_version_for_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> AgentVersion:
    await get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    result = await session.execute(
        select(AgentVersion)
        .where(
            AgentVersion.tenant_id == tenant_id,
            AgentVersion.agent_id == agent_id,
            AgentVersion.status == VERSION_STATUS_DRAFT,
        )
        .order_by(AgentVersion.version_number.desc())
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise ProductAgentNotFoundError("draft agent version not found for agent")
    return version


async def assert_workflow_exists_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workflow_id: UUID,
) -> None:
    result = await session.execute(
        select(Workflow.id).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise ProductAgentNotFoundError("workflow not found for tenant")


async def evaluate_builder_readiness(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> dict[str, Any]:
    version = await get_agent_version_for_tenant(
        session,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    knowledge_bindings = await _list_bindings_for_version(
        session,
        AgentKnowledgeSourceBinding,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    tool_bindings = await _list_bindings_for_version(
        session,
        AgentToolBinding,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    action_bindings = await _list_bindings_for_version(
        session,
        AgentActionBinding,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    field_permissions = await _list_bindings_for_version(
        session,
        AgentFieldPermission,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    workflow_bindings = await _list_bindings_for_version(
        session,
        AgentWorkflowBinding,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    deployments = await _list_deployments_for_version(
        session,
        tenant_id=tenant_id,
        version=version,
    )
    source_rows = await _list_sources_for_knowledge_bindings(
        session,
        tenant_id=tenant_id,
        bindings=knowledge_bindings,
    )
    latest_test_run = await _latest_test_run_for_version(
        session,
        tenant_id=tenant_id,
        version_id=version_id,
    )
    checks = [
        _identity_check(version),
        _knowledge_check(version, knowledge_bindings, source_rows),
        _tool_check(version, tool_bindings),
        _action_check(action_bindings),
        _field_policy_check(field_permissions),
        _workflow_check(workflow_bindings),
        _deployment_safety_check(deployments),
        _test_lab_readiness_check(latest_test_run),
    ]
    test_lab_check = checks[-1]
    blocking_codes = [check["code"] for check in checks if check["status"] == "block"]
    return {
        "status": "blocked" if blocking_codes else "ready",
        "version_id": version.id,
        "agent_id": version.agent_id,
        "checks": checks,
        "blocking_codes": blocking_codes,
        "safety": {flag_name: False for flag_name in SAFE_DEPLOYMENT_FLAGS},
        "test_lab_passed": test_lab_check["code"] == "test_lab_passed",
        "live_publish_allowed": False,
    }


async def evaluate_agent_builder_readiness(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
) -> dict[str, Any]:
    version = await get_draft_version_for_agent(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    return await evaluate_builder_readiness(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
    )


async def _list_bindings_for_version(
    session: AsyncSession,
    model,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> list[Any]:
    result = await session.execute(
        select(model).where(model.tenant_id == tenant_id, model.agent_version_id == version_id)
    )
    return list(result.scalars().all())


async def _list_deployments_for_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
) -> list[AgentDeployment]:
    result = await session.execute(
        select(AgentDeployment).where(
            AgentDeployment.tenant_id == tenant_id,
            AgentDeployment.agent_id == version.agent_id,
        )
    )
    return [
        deployment
        for deployment in result.scalars().all()
        if deployment.active_version_id in (None, version.id)
    ]


async def _list_sources_for_knowledge_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    bindings: list[AgentKnowledgeSourceBinding],
) -> dict[UUID, KnowledgeSource]:
    source_ids = [binding.knowledge_source_id for binding in bindings]
    if not source_ids:
        return {}
    result = await session.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id,
            KnowledgeSource.id.in_(source_ids),
        )
    )
    return {source.id: source for source in result.scalars().all()}


def _identity_check(version: AgentVersion) -> dict[str, Any]:
    missing = [
        field_name
        for field_name, value in {
            "role": version.role,
            "language": version.language,
            "instructions": version.instructions,
        }.items()
        if not value
    ]
    if missing:
        return {
            "code": "identity_incomplete",
            "label": "Identity",
            "status": "block",
            "message": "Draft identity is missing required fields.",
            "metadata": {"missing": missing},
        }
    return {
        "code": "identity_ready",
        "label": "Identity",
        "status": "pass",
        "message": "Draft identity has required fields.",
        "metadata": {},
    }


def _knowledge_check(
    version: AgentVersion,
    bindings: list[AgentKnowledgeSourceBinding],
    sources: dict[UUID, KnowledgeSource],
) -> dict[str, Any]:
    requires_knowledge = bool(version.knowledge_policy.get("requires_knowledge", False))
    required_bindings = [binding for binding in bindings if binding.required]
    if not required_bindings:
        return {
            "code": "knowledge_sources_bound" if bindings else "required_knowledge_missing",
            "label": "Knowledge sources",
            "status": "block" if requires_knowledge or not bindings else "warn",
            "message": (
                "Required knowledge source binding is missing."
                if requires_knowledge or not bindings
                else "No required knowledge binding yet."
            ),
            "metadata": {"required": requires_knowledge, "bound": len(bindings)},
        }
    unhealthy = []
    for binding in required_bindings:
        source = sources.get(binding.knowledge_source_id)
        if source is None:
            unhealthy.append(
                {
                    "source_id": str(binding.knowledge_source_id),
                    "reason": "source_missing",
                }
            )
            continue
        source_health = _source_health(source)
        if source_health["blocker"]:
            unhealthy.append(
                {
                    "source_id": str(source.id),
                    "source_name": source.name,
                    "reason": source_health["blocker_reason"],
                    "status": source_health["status"],
                }
            )
    if unhealthy:
        return {
            "code": "knowledge_sources_healthy",
            "label": "Knowledge sources",
            "status": "block",
            "message": "Esta fuente no esta lista para publicar.",
            "metadata": {
                "bound": len(bindings),
                "required": len(required_bindings),
                "unhealthy": unhealthy,
            },
        }
    status = "pass" if bindings else "warn"
    return {
        "code": "knowledge_sources_healthy" if bindings else "knowledge_sources_empty",
        "label": "Knowledge sources",
        "status": status,
        "message": (
            "Knowledge connected." if bindings else "No knowledge binding yet."
        ),
        "metadata": {"bound": len(bindings), "required": len(required_bindings)},
    }


def _tool_check(version: AgentVersion, bindings: list[AgentToolBinding]) -> dict[str, Any]:
    required_tools = set(version.tool_policy.get("required_tools") or [])
    bound_tools = {binding.tool_name for binding in bindings if binding.enabled}
    missing = sorted(required_tools - bound_tools)
    if missing:
        return {
            "code": "required_tools_missing",
            "label": "Tools",
            "status": "block",
            "message": "Required tool binding is missing.",
            "metadata": {"missing": missing},
        }
    return {
        "code": "tools_ready" if bindings else "tools_empty",
        "label": "Tools",
        "status": "pass" if bindings else "warn",
        "message": "Tool bindings are configured." if bindings else "No tool binding yet.",
        "metadata": {"bound": len(bindings)},
    }


def _action_check(bindings: list[AgentActionBinding]) -> dict[str, Any]:
    unsafe = [
        binding.action_key
        for binding in bindings
        if _action_binding_blocker(binding) is not None
    ]
    if unsafe:
        return {
            "code": "actions_unsafe",
            "label": "Actions",
            "status": "block",
            "message": "Action binding needs safe execution mode and permissions.",
            "metadata": {"unsafe": unsafe},
        }
    return {
        "code": "actions_ready" if bindings else "actions_empty",
        "label": "Actions",
        "status": "pass" if bindings else "warn",
        "message": "Action bindings are safe." if bindings else "No action binding yet.",
        "metadata": {"bound": len(bindings)},
    }


def _field_policy_check(bindings: list[AgentFieldPermission]) -> dict[str, Any]:
    unsafe = [
        binding.field_key
        for binding in bindings
        if binding.can_write and not binding.evidence_required
    ]
    if unsafe:
        return {
            "code": "field_policy_unsafe",
            "label": "Field policy",
            "status": "block",
            "message": "Writable fields need evidence policy.",
            "metadata": {"unsafe": unsafe},
        }
    return {
        "code": "field_policy_ready" if bindings else "field_policy_empty",
        "label": "Field policy",
        "status": "pass" if bindings else "warn",
        "message": "Field policy is configured." if bindings else "No field policy yet.",
        "metadata": {"bound": len(bindings)},
    }


def _workflow_check(bindings: list[AgentWorkflowBinding]) -> dict[str, Any]:
    unsafe = [
        str(binding.workflow_id)
        for binding in bindings
        if binding.enabled
        and (binding.side_effects_allowed or binding.customer_visible_output_allowed)
    ]
    if unsafe:
        return {
            "code": "workflow_bindings_unsafe",
            "label": "Workflows",
            "status": "block",
            "message": (
                "Workflow bindings cannot allow side effects or visible copy in Builder MVP."
            ),
            "metadata": {"unsafe": unsafe},
        }
    return {
        "code": "workflows_ready" if bindings else "workflows_empty",
        "label": "Workflows",
        "status": "pass" if bindings else "warn",
        "message": "Workflow bindings are safe." if bindings else "No workflow binding yet.",
        "metadata": {"bound": len(bindings)},
    }


def _validate_test_suite_mode(mode: str) -> None:
    if mode not in TEST_SUITE_MODES:
        raise TestLabValidationError("test suite mode is not allowed")


def _validate_test_scenario_payload(
    *,
    turns: list[dict[str, Any]],
    expected: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    if not isinstance(turns, list):
        raise TestLabValidationError("scenario turns must be a JSON list")
    if not turns:
        raise TestLabValidationError("scenario must include at least one turn")
    for turn in turns:
        if not isinstance(turn, dict):
            raise TestLabValidationError("each scenario turn must be a JSON object")
        inbound = turn.get("inbound_text") or turn.get("text") or turn.get("message")
        if not isinstance(inbound, str) or not inbound.strip():
            raise TestLabValidationError("each scenario turn must include inbound text")
        attachments = turn.get("attachments")
        if attachments is not None and not isinstance(attachments, list):
            raise TestLabValidationError("scenario turn attachments must be a JSON list")
        turn_expected = turn.get("expected")
        if turn_expected is not None and not isinstance(turn_expected, dict):
            raise TestLabValidationError("scenario turn expected must be a JSON object")
    if not isinstance(expected, dict):
        raise TestLabValidationError("scenario expected must be a JSON object")
    expected_turns = (
        expected.get("turns") if "turns" in expected else expected.get("expected_turns")
    )
    if expected_turns is not None:
        if not isinstance(expected_turns, list):
            raise TestLabValidationError("scenario expected turns must be a JSON list")
        if not all(isinstance(item, dict) for item in expected_turns):
            raise TestLabValidationError("each expected turn must be a JSON object")
    for key in ("required_tools", "expected_tools", "state_writes", "expected_state_writes"):
        value = expected.get(key)
        if value is not None and not isinstance(value, list):
            raise TestLabValidationError(f"scenario expected {key} must be a JSON list")
    if not isinstance(metadata, dict):
        raise TestLabValidationError("scenario metadata must be a JSON object")


async def _assert_tenant_id_shape(tenant_id: UUID) -> None:
    if not isinstance(tenant_id, UUID):
        raise ProductAgentError("tenant_id must be a UUID")


def _require_capability(key: str, *, kind: CapabilityKind) -> ProductCapability:
    capability = get_capability(key, kind=kind)
    if capability is None:
        raise ProductAgentNotFoundError(f"{kind} capability not found")
    return capability


def _validate_action_binding_against_capability(
    capability: ProductCapability,
    *,
    enabled: bool,
    execution_mode: str,
    permissions: dict[str, Any],
) -> None:
    if execution_mode in BLOCKED_ACTION_LIVE_MODES:
        raise ProductAgentError("live action modes are blocked in Product-First Builder")
    validate_action_permissions(
        execution_mode=execution_mode,
        permissions=permissions,
        enabled=enabled,
    )
    if capability.key == "send_message" and enabled:
        raise ProductAgentError("send_message cannot be enabled from Agent Builder")
    missing_permissions = [
        permission
        for permission in capability.required_permissions
        if permission not in permissions
    ]
    if enabled and missing_permissions:
        raise ProductAgentError("enabled action is missing required permissions")
    if enabled and capability.required_auth and not permissions.get("auth_configured"):
        raise ProductAgentError("enabled action requires auth configuration")


def _capability_option(capability: ProductCapability) -> dict[str, Any]:
    return {
        "key": capability.key,
        "label": capability.label,
        "kind": capability.kind,
        "category": capability.category,
        "description": capability.description,
        "risk_level": capability.risk_level,
        "side_effect_type": capability.side_effect_type,
        "has_side_effects": capability.has_side_effects,
        "default_mode": capability.default_mode,
        "required_auth": capability.required_auth,
        "required_permissions": list(capability.required_permissions),
        "input_schema": capability.input_schema,
        "output_schema": capability.output_schema,
        "publish_blockers": list(capability.publish_blockers),
    }


def _tool_binding_read(binding: AgentToolBinding, *, agent_id: UUID) -> dict[str, Any]:
    capability = get_capability(binding.tool_name, kind="tool")
    blocker = capability is None
    return {
        "id": binding.id,
        "tenant_id": binding.tenant_id,
        "agent_id": agent_id,
        "agent_version_id": binding.agent_version_id,
        "tool_name": binding.tool_name,
        "label": capability.label if capability else binding.tool_name,
        "category": capability.category if capability else "unknown",
        "enabled": binding.enabled,
        "required": binding.required,
        "risk_level": capability.risk_level if capability else "unknown",
        "side_effect_type": capability.side_effect_type if capability else "unknown",
        "has_side_effects": capability.has_side_effects if capability else True,
        "blocker": blocker,
        "blocker_reason": "unknown_tool" if blocker else None,
        "input_schema": binding.input_schema or {},
        "output_schema": binding.output_schema or {},
        "metadata": binding.metadata_json or {},
    }


def _action_binding_read(binding: AgentActionBinding, *, agent_id: UUID) -> dict[str, Any]:
    capability = get_capability(binding.action_key, kind="action")
    blocker_reason = _action_binding_blocker(binding)
    return {
        "id": binding.id,
        "tenant_id": binding.tenant_id,
        "agent_id": agent_id,
        "agent_version_id": binding.agent_version_id,
        "action_key": binding.action_key,
        "label": capability.label if capability else binding.action_key,
        "category": capability.category if capability else "unknown",
        "enabled": binding.enabled,
        "execution_mode": binding.execution_mode,
        "approval_required": binding.approval_required,
        "risk_level": capability.risk_level if capability else "unknown",
        "side_effect_type": capability.side_effect_type if capability else "unknown",
        "has_side_effects": capability.has_side_effects if capability else True,
        "required_auth": capability.required_auth if capability else True,
        "required_permissions": list(capability.required_permissions) if capability else [],
        "permissions": binding.permissions or {},
        "blocker": blocker_reason is not None,
        "blocker_reason": blocker_reason,
        "publish_blockers": list(capability.publish_blockers) if capability else ["unknown_action"],
        "metadata": binding.metadata_json or {},
    }


def _action_binding_blocker(binding: AgentActionBinding) -> str | None:
    capability = get_capability(binding.action_key, kind="action")
    if capability is None:
        return "unknown_action"
    if binding.execution_mode in BLOCKED_ACTION_LIVE_MODES:
        return "live_mode_blocked"
    if binding.enabled and binding.execution_mode == "disabled":
        return "enabled_action_disabled_mode"
    if binding.enabled and capability.key == "send_message":
        return "send_message_blocked"
    if binding.enabled and capability.required_auth and not (binding.permissions or {}).get(
        "auth_configured"
    ):
        return "auth_required"
    missing_permissions = [
        permission
        for permission in capability.required_permissions
        if permission not in (binding.permissions or {})
    ]
    if binding.enabled and missing_permissions:
        return "permissions_required"
    if binding.enabled and capability.has_side_effects and not binding.approval_required:
        return "approval_required"
    return None


def _deployment_safety_check(deployments: list[AgentDeployment]) -> dict[str, Any]:
    enabled = {
        str(deployment.id): [
            flag_name
            for flag_name in SAFE_DEPLOYMENT_FLAGS
            if bool(getattr(deployment, flag_name, False))
        ]
        for deployment in deployments
    }
    enabled = {deployment_id: flags for deployment_id, flags in enabled.items() if flags}
    if enabled:
        return {
            "code": "live_flags_enabled",
            "label": "Deployment safety",
            "status": "block",
            "message": "Deployment has live side-effect flags enabled.",
            "metadata": {"enabled": enabled},
        }
    return {
        "code": "deployment_safety_ready",
        "label": "Deployment safety",
        "status": "pass",
        "message": "No live send, outbox, action, workflow, canary, or production flag is enabled.",
        "metadata": {"deployments": len(deployments)},
    }


def _test_lab_readiness_check(latest_run: AgentTestRun | None) -> dict[str, Any]:
    if latest_run is None:
        return {
            "code": "test_lab_not_run",
            "label": "Test Lab",
            "status": "warn",
            "message": "No DB-backed no-send Test Lab run has been recorded yet.",
            "metadata": {},
        }
    execution_mode = str((latest_run.coverage_summary or {}).get("execution_mode") or "")
    if latest_run.status == "passed" and latest_run.decision == "TEST_LAB_PASSED":
        if execution_mode != "runtime_v2_agent_service":
            return {
                "code": "test_lab_runtime_v2_required",
                "label": "Test Lab",
                "status": "block",
                "message": (
                    "Latest Test Lab run passed outside Runtime V2 AgentService mode; "
                    "it cannot mark publish readiness."
                ),
                "metadata": {
                    "test_run_id": str(latest_run.id),
                    "decision": latest_run.decision,
                    "execution_mode": execution_mode or "unknown",
                },
            }
        return {
            "code": "test_lab_passed",
            "label": "Test Lab",
            "status": "pass",
            "message": "Latest DB-backed no-send Test Lab run passed.",
            "metadata": {
                "test_run_id": str(latest_run.id),
                "decision": latest_run.decision,
                "execution_mode": execution_mode,
                "trace_count": len(latest_run.trace_ids or []),
            },
        }
    return {
        "code": "test_lab_failed",
        "label": "Test Lab",
        "status": "block",
        "message": "Latest DB-backed no-send Test Lab run failed or is blocked.",
        "metadata": {
            "test_run_id": str(latest_run.id),
            "status": latest_run.status,
            "decision": latest_run.decision,
            "execution_mode": execution_mode or "unknown",
        },
    }


async def _latest_test_run_for_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> AgentTestRun | None:
    result = await session.execute(
        select(AgentTestRun)
        .where(
            AgentTestRun.tenant_id == tenant_id,
            AgentTestRun.agent_version_id == version_id,
        )
        .order_by(AgentTestRun.created_at.desc())
    )
    return result.scalar_one_or_none()


def _test_run_snapshot(run: AgentTestRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "status": run.status,
        "decision": run.decision,
        "pass_count": run.pass_count,
        "fail_count": run.fail_count,
        "blocked_count": run.blocked_count,
        "trace_ids": [str(trace_id) for trace_id in run.trace_ids],
        "outbox_audit_result": run.outbox_audit_result,
        "side_effect_audit_result": run.side_effect_audit_result,
    }


def _publish_request_blockers(
    *,
    publish_request: AgentPublishRequest,
    deployment: AgentDeployment,
    version: AgentVersion,
    readiness: dict[str, Any],
    latest_run: AgentTestRun | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if publish_request.requested_state not in PUBLISH_REQUEST_STATES:
        blockers.append(_publish_blocker("requested_state_not_allowed"))
    if publish_request.send_scope not in PUBLISH_REQUEST_SEND_SCOPES:
        blockers.append(_publish_blocker("send_scope_not_allowed"))
    if version.agent_id != deployment.agent_id:
        blockers.append(_publish_blocker("version_deployment_agent_mismatch"))
    if deployment.active_version_id not in (None, version.id):
        blockers.append(_publish_blocker("deployment_version_mismatch"))
    unsafe_flags = [
        flag_name
        for flag_name in SAFE_DEPLOYMENT_FLAGS
        if bool(getattr(deployment, flag_name, False))
    ]
    if unsafe_flags:
        blockers.append(_publish_blocker("deployment_live_flags_enabled", flags=unsafe_flags))
    if publish_request.rollback_version_id is None:
        blockers.append(_publish_blocker("rollback_target_missing"))
    if readiness.get("blocking_codes"):
        blockers.append(
            _publish_blocker(
                "builder_readiness_blocked",
                blocking_codes=list(readiness["blocking_codes"]),
            )
        )
    blockers.extend(_test_lab_blockers(latest_run))
    return blockers


def _test_lab_blockers(run: AgentTestRun | None) -> list[dict[str, Any]]:
    if run is None:
        return [_publish_blocker("test_lab_run_missing")]
    blockers: list[dict[str, Any]] = []
    if run.status != "passed" or run.decision != "TEST_LAB_PASSED":
        blockers.append(_publish_blocker("test_lab_not_passed", status=run.status))
    execution_mode = str((run.coverage_summary or {}).get("execution_mode") or "")
    if execution_mode != "runtime_v2_agent_service":
        blockers.append(
            _publish_blocker(
                "test_lab_runtime_v2_required",
                execution_mode=execution_mode or "unknown",
            )
        )
    if not run.trace_ids:
        blockers.append(_publish_blocker("trace_ids_missing"))
    if not _audit_passed(run.outbox_audit_result):
        blockers.append(_publish_blocker("outbox_audit_not_zero", audit=run.outbox_audit_result))
    if not _audit_passed(run.side_effect_audit_result):
        blockers.append(
            _publish_blocker("side_effect_audit_not_zero", audit=run.side_effect_audit_result)
        )
    return blockers


def _audit_passed(audit: dict[str, Any]) -> bool:
    return audit.get("status") == "pass" and int(audit.get("count", 0)) == 0


def _publish_blocker(code: str, **metadata: Any) -> dict[str, Any]:
    return {"code": code, "metadata": metadata}


def _advance_deployment_to_ready_for_no_send(deployment: AgentDeployment) -> None:
    path = {
        DEPLOYMENT_STATE_DRAFT: DEPLOYMENT_STATE_TEST_REQUIRED,
        DEPLOYMENT_STATE_TEST_REQUIRED: DEPLOYMENT_STATE_TEST_PASSED,
        DEPLOYMENT_STATE_TEST_PASSED: DEPLOYMENT_STATE_READY_FOR_APPROVAL,
    }
    while deployment.publish_state in path:
        apply_deployment_state_transition(deployment, to_state=path[deployment.publish_state])


def _source_option(source: KnowledgeSource, bound_agent_ids: list[UUID]) -> dict[str, Any]:
    health = _source_health(source)
    metadata = _source_metadata(source)
    return {
        "id": source.id,
        "tenant_id": source.tenant_id,
        "name": source.name,
        "source_type": _source_type(source),
        "content_type": source.content_type,
        "status": health["status"],
        "health": health["health"],
        "parser_status": metadata.get("parser_status"),
        "index_status": metadata.get("index_status"),
        "checksum": _string_metadata(metadata, "checksum", "content_checksum"),
        "version": _string_metadata(metadata, "version", "source_version"),
        "last_indexed_at": _string_metadata(metadata, "last_indexed_at", "last_indexed"),
        "error_message": _redacted_error(metadata, blocker=health["blocker"]),
        "bound_agent_ids": bound_agent_ids,
        "blocker": health["blocker"],
        "blocker_reason": health["blocker_reason"],
        "metadata": {
            "priority": source.priority,
            "owner": source.owner,
        },
    }


def _knowledge_binding_read(
    binding: AgentKnowledgeSourceBinding,
    source: KnowledgeSource,
    *,
    agent_id: UUID,
) -> dict[str, Any]:
    option = _source_option(source, [agent_id])
    return {
        "id": binding.id,
        "tenant_id": binding.tenant_id,
        "agent_id": agent_id,
        "agent_version_id": binding.agent_version_id,
        "knowledge_source_id": binding.knowledge_source_id,
        "source_name": source.name,
        "source_type": option["source_type"],
        "status": option["status"],
        "health": option["health"],
        "required": binding.required,
        "binding_mode": binding.binding_mode,
        "priority": binding.priority,
        "blocker": option["blocker"],
        "blocker_reason": option["blocker_reason"],
        "checksum": option["checksum"],
        "version": option["version"],
        "last_indexed_at": option["last_indexed_at"],
        "error_message": option["error_message"],
        "metadata": binding.metadata_json or {},
    }


def _source_health(source: KnowledgeSource) -> dict[str, Any]:
    metadata = _source_metadata(source)
    status = str(source.status or "missing").lower()
    health_status = str(metadata.get("health") or metadata.get("health_status") or "").lower()
    if health_status in SOURCE_UNHEALTHY_STATUSES:
        return {
            "status": status,
            "health": "unhealthy",
            "blocker": True,
            "blocker_reason": SOURCE_HEALTH_BLOCKERS.get(health_status, "source_unhealthy"),
        }
    if status in SOURCE_HEALTHY_STATUSES:
        return {
            "status": status,
            "health": "healthy",
            "blocker": False,
            "blocker_reason": None,
        }
    if status in SOURCE_PENDING_STATUSES:
        return {
            "status": status,
            "health": "pending",
            "blocker": True,
            "blocker_reason": SOURCE_HEALTH_BLOCKERS.get(status, "source_not_indexed"),
        }
    return {
        "status": status,
        "health": "unhealthy",
        "blocker": True,
        "blocker_reason": SOURCE_HEALTH_BLOCKERS.get(status, "source_unhealthy"),
    }


def _source_metadata(source: KnowledgeSource) -> dict[str, Any]:
    metadata = source.metadata_json or {}
    return metadata if isinstance(metadata, dict) else {}


def _source_type(source: KnowledgeSource) -> str:
    metadata = _source_metadata(source)
    source_type = str(metadata.get("source_type") or source.type or source.content_type)
    aliases = {
        "table": "catalog",
        "file": "document",
        "manual": "document",
        "expediente_contract": "expediente",
    }
    return aliases.get(source_type.lower(), source_type.lower())


def _string_metadata(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _redacted_error(metadata: dict[str, Any], *, blocker: bool) -> str | None:
    error = _string_metadata(
        metadata,
        "error_message_redacted",
        "last_error_message_redacted",
        "error_redacted",
        "last_error_code",
    )
    if error:
        return error[:180]
    if blocker and _string_metadata(metadata, "error_message", "last_error_message"):
        return "Error redacted. See source trace."
    return None

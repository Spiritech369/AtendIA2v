from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.product_agent import AgentDeployment, AgentVersion
from atendia.db.session import get_db_session
from atendia.product_agents import service, test_lab
from atendia.product_agents.schemas import (
    ActionBindingCreate,
    AgentActionBindingCreate,
    AgentActionBindingRead,
    AgentBuilderConfigUpdate,
    AgentBuilderReadinessRead,
    AgentBuilderStateRead,
    AgentDeploymentCreate,
    AgentDeploymentRead,
    AgentDeploymentTransitionRequest,
    AgentKnowledgeBindingCreate,
    AgentKnowledgeBindingRead,
    AgentPublishRequestCreate,
    AgentPublishRequestDecision,
    AgentPublishRequestRead,
    AgentTestRunCreate,
    AgentTestRunRead,
    AgentTestScenarioCreate,
    AgentTestScenarioRead,
    AgentTestSuiteCreate,
    AgentTestSuiteRead,
    AgentToolBindingCreate,
    AgentToolBindingRead,
    AgentVersionCreate,
    AgentVersionRead,
    AgentVersionUpdate,
    BuilderOptionsRead,
    CapabilityOptionRead,
    KnowledgeSourceBindingCreate,
    KnowledgeSourceOptionRead,
    ProductAgentCreate,
    ProductAgentRead,
    ProductAgentUpdate,
    ToolBindingCreate,
)

router = APIRouter()


def _http_error(exc: service.ProductAgentError) -> HTTPException:
    if isinstance(exc, service.ProductAgentNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, service.ImmutableAgentVersionError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, service.PublishStateTransitionError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/agents", response_model=list[ProductAgentRead])
async def list_product_agents(
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await service.list_product_agents(session, tenant_id=tenant_id)


@router.post(
    "/agents",
    response_model=ProductAgentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_agent(
    payload: ProductAgentCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    agent = await service.create_product_agent(
        session,
        tenant_id=tenant_id,
        name=payload.name,
        role=payload.role,
        tone=payload.tone,
        language=payload.language,
        instructions=payload.instructions,
    )
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get("/builder/options", response_model=BuilderOptionsRead)
async def list_builder_options(
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await service.list_builder_options(session, tenant_id=tenant_id)


@router.get("/knowledge-sources/options", response_model=list[KnowledgeSourceOptionRead])
async def list_knowledge_source_options(
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await service.list_knowledge_source_options(session, tenant_id=tenant_id)


@router.get("/tools/options", response_model=list[CapabilityOptionRead])
async def list_tool_options(
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await service.list_tool_options(session, tenant_id=tenant_id)


@router.get("/actions/options", response_model=list[CapabilityOptionRead])
async def list_action_options(
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await service.list_action_options(session, tenant_id=tenant_id)


@router.get("/agents/{agent_id}", response_model=ProductAgentRead)
async def get_product_agent(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.get_agent_for_tenant(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.patch("/agents/{agent_id}", response_model=ProductAgentRead)
async def update_product_agent(
    agent_id: UUID,
    payload: ProductAgentUpdate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        agent = await service.update_product_agent(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            values=payload.model_dump(exclude_unset=True),
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get(
    "/agents/{agent_id}/knowledge-bindings",
    response_model=list[AgentKnowledgeBindingRead],
)
async def list_agent_knowledge_bindings(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.list_agent_knowledge_bindings(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/{agent_id}/knowledge-bindings",
    response_model=AgentKnowledgeBindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def bind_agent_knowledge_source(
    agent_id: UUID,
    payload: AgentKnowledgeBindingCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        binding = await service.bind_agent_knowledge_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            knowledge_source_id=payload.knowledge_source_id,
            binding_mode=payload.binding_mode,
            required=payload.required,
            priority=payload.priority,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return binding


@router.delete(
    "/agents/{agent_id}/knowledge-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_agent_knowledge_source(
    agent_id: UUID,
    binding_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        await service.unbind_agent_knowledge_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            binding_id=binding_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return None


@router.get(
    "/agents/{agent_id}/tool-bindings",
    response_model=list[AgentToolBindingRead],
)
async def list_agent_tool_bindings(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.list_agent_tool_bindings(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/{agent_id}/tool-bindings",
    response_model=AgentToolBindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def bind_agent_tool(
    agent_id: UUID,
    payload: AgentToolBindingCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        binding = await service.bind_agent_tool(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            tool_name=payload.tool_name,
            enabled=payload.enabled,
            required=payload.required,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return binding


@router.delete(
    "/agents/{agent_id}/tool-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_agent_tool(
    agent_id: UUID,
    binding_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        await service.unbind_agent_tool(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            binding_id=binding_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return None


@router.get(
    "/agents/{agent_id}/action-bindings",
    response_model=list[AgentActionBindingRead],
)
async def list_agent_action_bindings(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.list_agent_action_bindings(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/{agent_id}/action-bindings",
    response_model=AgentActionBindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def bind_agent_action(
    agent_id: UUID,
    payload: AgentActionBindingCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        binding = await service.bind_agent_action(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            action_key=payload.action_key,
            enabled=payload.enabled,
            execution_mode=payload.execution_mode,
            permissions=payload.permissions,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return binding


@router.delete(
    "/agents/{agent_id}/action-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_agent_action(
    agent_id: UUID,
    binding_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        await service.unbind_agent_action(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            binding_id=binding_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return None


@router.get("/agents/{agent_id}/readiness", response_model=AgentBuilderReadinessRead)
async def get_agent_readiness(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.evaluate_agent_builder_readiness(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.get("/agents/{agent_id}/builder-state", response_model=AgentBuilderStateRead)
async def get_agent_builder_state(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.get_agent_builder_state(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/{agent_id}/draft-version",
    response_model=AgentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_builder_draft_version(
    agent_id: UUID,
    payload: AgentVersionCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        version = await service.create_builder_draft_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            payload=payload.model_dump(),
            created_by_user_id=user.user_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(version)
    return version


@router.get("/agents/{agent_id}/versions", response_model=list[AgentVersionRead])
async def list_agent_versions(
    agent_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    await service.get_agent_for_tenant(session, tenant_id=tenant_id, agent_id=agent_id)
    result = await session.execute(
        select(AgentVersion)
        .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/agents/{agent_id}/versions",
    response_model=AgentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_version(
    agent_id: UUID,
    payload: AgentVersionCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        version = await service.create_agent_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            payload=payload.model_dump(),
            created_by_user_id=user.user_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(version)
    return version


@router.patch("/versions/{version_id}", response_model=AgentVersionRead)
async def update_agent_version(
    version_id: UUID,
    payload: AgentVersionUpdate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        version = await service.update_agent_version(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
            values=payload.model_dump(exclude_unset=True),
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(version)
    return version


@router.patch("/versions/{version_id}/builder-config", response_model=AgentVersionRead)
async def update_agent_builder_config(
    version_id: UUID,
    payload: AgentBuilderConfigUpdate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        version = await service.update_agent_version(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
            values=payload.model_dump(exclude_unset=True),
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(version)
    return version


@router.get("/versions/{version_id}/readiness", response_model=AgentBuilderReadinessRead)
async def get_agent_builder_readiness(
    version_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.evaluate_builder_readiness(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.get("/versions/{version_id}/test-suites", response_model=list[AgentTestSuiteRead])
async def list_agent_test_suites(
    version_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.list_agent_test_suites(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/versions/{version_id}/test-suites",
    response_model=AgentTestSuiteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_test_suite(
    version_id: UUID,
    payload: AgentTestSuiteCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        suite = await service.create_agent_test_suite(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
            name=payload.name,
            mode=payload.mode,
            metadata=payload.metadata,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(suite)
    return suite


@router.get("/test-suites/{suite_id}/scenarios", response_model=list[AgentTestScenarioRead])
async def list_agent_test_scenarios(
    suite_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.list_agent_test_scenarios(
            session,
            tenant_id=tenant_id,
            suite_id=suite_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/test-suites/{suite_id}/scenarios",
    response_model=AgentTestScenarioRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_test_scenario(
    suite_id: UUID,
    payload: AgentTestScenarioCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        scenario = await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite_id,
            name=payload.name,
            turns=payload.turns,
            expected=payload.expected,
            metadata=payload.metadata,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(scenario)
    return scenario


@router.post(
    "/test-suites/{suite_id}/runs",
    response_model=AgentTestRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_agent_test_suite(
    suite_id: UUID,
    payload: AgentTestRunCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        run = await test_lab.run_test_suite(
            session,
            tenant_id=tenant_id,
            suite_id=suite_id,
            mode=payload.mode,
            execution_mode=payload.execution_mode,
            review_required=payload.review_required,
            created_by_user_id=user.user_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(run)
    return run


@router.get("/test-suites/{suite_id}/runs/latest", response_model=AgentTestRunRead | None)
async def get_latest_agent_test_run(
    suite_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.get_latest_agent_test_run(
            session,
            tenant_id=tenant_id,
            suite_id=suite_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post("/versions/{version_id}/publish", response_model=AgentVersionRead)
async def publish_agent_version(
    version_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        version = await service.publish_agent_version(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(version)
    return version


@router.get("/deployments", response_model=list[AgentDeploymentRead])
async def list_agent_deployments(
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(AgentDeployment)
        .where(AgentDeployment.tenant_id == tenant_id)
        .order_by(AgentDeployment.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/deployments",
    response_model=AgentDeploymentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_deployment(
    payload: AgentDeploymentCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        deployment = await service.create_agent_deployment(
            session,
            tenant_id=tenant_id,
            agent_id=payload.agent_id,
            name=payload.name,
            channel=payload.channel,
            environment=payload.environment,
            active_version_id=payload.active_version_id,
            created_by_user_id=user.user_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(deployment)
    return deployment


@router.post("/deployments/{deployment_id}/transition", response_model=AgentDeploymentRead)
async def transition_agent_deployment(
    deployment_id: UUID,
    payload: AgentDeploymentTransitionRequest,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        deployment = await service.transition_agent_deployment(
            session,
            tenant_id=tenant_id,
            deployment_id=deployment_id,
            to_state=payload.to_state,
            actor_user_id=user.user_id,
            reason=payload.reason,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(deployment)
    return deployment


@router.post(
    "/deployments/{deployment_id}/publish-requests",
    response_model=AgentPublishRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_publish_request(
    deployment_id: UUID,
    payload: AgentPublishRequestCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        publish_request = await service.create_publish_request(
            session,
            tenant_id=tenant_id,
            deployment_id=deployment_id,
            agent_version_id=payload.agent_version_id,
            requested_state=payload.requested_state,
            send_scope=payload.send_scope,
            channel_scope=payload.channel_scope,
            audience_scope=payload.audience_scope,
            rollback_version_id=payload.rollback_version_id,
            approval_text=payload.approval_text,
            requested_by_user_id=user.user_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(publish_request)
    return publish_request


@router.get(
    "/deployments/{deployment_id}/publish-requests/latest",
    response_model=AgentPublishRequestRead | None,
)
async def get_latest_publish_request(
    deployment_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await service.get_latest_publish_request(
            session,
            tenant_id=tenant_id,
            deployment_id=deployment_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/publish-requests/{request_id}/evaluate",
    response_model=AgentPublishRequestRead,
)
async def evaluate_publish_request(
    request_id: UUID,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        publish_request = await service.evaluate_publish_request(
            session,
            tenant_id=tenant_id,
            request_id=request_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(publish_request)
    return publish_request


@router.post(
    "/publish-requests/{request_id}/approve-no-send",
    response_model=AgentPublishRequestRead,
)
async def approve_publish_request_no_send(
    request_id: UUID,
    payload: AgentPublishRequestDecision,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        publish_request = await service.approve_publish_request_no_send(
            session,
            tenant_id=tenant_id,
            request_id=request_id,
            approved_by_user_id=user.user_id,
            approval_text=payload.approval_text,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(publish_request)
    return publish_request


@router.post(
    "/publish-requests/{request_id}/reject",
    response_model=AgentPublishRequestRead,
)
async def reject_publish_request(
    request_id: UUID,
    payload: AgentPublishRequestDecision,
    tenant_id: UUID = Depends(current_tenant_id),
    user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        publish_request = await service.reject_publish_request(
            session,
            tenant_id=tenant_id,
            request_id=request_id,
            actor_user_id=user.user_id,
            reason=payload.reason,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    await session.refresh(publish_request)
    return publish_request


@router.post("/versions/{version_id}/tool-bindings", status_code=status.HTTP_201_CREATED)
async def create_tool_binding(
    version_id: UUID,
    payload: ToolBindingCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        binding = await service.create_tool_binding(
            session,
            tenant_id=tenant_id,
            agent_version_id=version_id,
            tool_name=payload.tool_name,
            input_schema=payload.input_schema,
            output_schema=payload.output_schema,
            required=payload.required,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return {"id": binding.id, "tool_name": binding.tool_name}


@router.post("/versions/{version_id}/action-bindings", status_code=status.HTTP_201_CREATED)
async def create_action_binding(
    version_id: UUID,
    payload: ActionBindingCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        binding = await service.create_action_binding(
            session,
            tenant_id=tenant_id,
            agent_version_id=version_id,
            action_key=payload.action_key,
            execution_mode=payload.execution_mode,
            permissions=payload.permissions,
            enabled=payload.enabled,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return {"id": binding.id, "action_key": binding.action_key}


@router.post(
    "/versions/{version_id}/knowledge-source-bindings",
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_source_binding(
    version_id: UUID,
    payload: KnowledgeSourceBindingCreate,
    tenant_id: UUID = Depends(current_tenant_id),
    _user: AuthUser = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        binding = await service.create_knowledge_source_binding(
            session,
            tenant_id=tenant_id,
            agent_version_id=version_id,
            knowledge_source_id=payload.knowledge_source_id,
        )
    except service.ProductAgentError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return {"id": binding.id, "knowledge_source_id": binding.knowledge_source_id}

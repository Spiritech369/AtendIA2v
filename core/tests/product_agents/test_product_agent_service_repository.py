from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.product_agent import AgentDeployment, AgentVersion
from atendia.product_agents import service


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeResult:
    def __init__(self, scalar=None, values=None):
        self._scalar = scalar
        self._values = values or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.flush_count = 0

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


def _agent(tenant_id, agent_id=None):
    return Agent(
        id=agent_id or uuid4(),
        tenant_id=tenant_id,
        name="Agent",
        role="custom",
        status="draft",
    )


def _version(tenant_id, agent_id=None, version_id=None):
    return AgentVersion(
        id=version_id or uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id or uuid4(),
        version_number=1,
        status="draft",
        is_immutable=False,
    )


def _deployment(tenant_id, agent_id=None, deployment_id=None):
    return AgentDeployment(
        id=deployment_id or uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id or uuid4(),
        name="Deployment",
        publish_state="ready_for_approval",
    )


@pytest.mark.asyncio
async def test_get_agent_for_tenant_returns_agent_or_raises() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)

    assert await service.get_agent_for_tenant(
        FakeSession(FakeResult(agent)),
        tenant_id=tenant_id,
        agent_id=agent.id,
    ) is agent
    with pytest.raises(service.ProductAgentNotFoundError):
        await service.get_agent_for_tenant(
            FakeSession(FakeResult(None)),
            tenant_id=tenant_id,
            agent_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_list_and_update_product_agent() -> None:
    tenant_id = uuid4()
    session = FakeSession()

    created = await service.create_product_agent(
        session,
        tenant_id=tenant_id,
        name="Builder Agent",
        role="custom",
        tone="calm",
        language="es",
        instructions="Help.",
    )

    assert created.tenant_id == tenant_id
    assert created.status == "draft"
    assert created.ops_config == {"product_first": True}
    assert session.added == [created]
    assert session.flush_count == 1

    agents = [_agent(tenant_id), _agent(tenant_id)]
    listed = await service.list_product_agents(
        FakeSession(FakeResult(values=agents)),
        tenant_id=tenant_id,
    )
    assert listed == agents

    agent = _agent(tenant_id)
    updated = await service.update_product_agent(
        FakeSession(FakeResult(agent)),
        tenant_id=tenant_id,
        agent_id=agent.id,
        values={"name": "Updated", "instructions": "New instructions"},
    )
    assert updated.name == "Updated"
    assert updated.system_prompt == "New instructions"


@pytest.mark.asyncio
async def test_create_update_and_publish_agent_version() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    actor_id = uuid4()
    session = FakeSession(FakeResult(agent), FakeResult(2))

    version = await service.create_agent_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent.id,
        payload={"role": "support", "snapshot": {"a": 1}},
        created_by_user_id=actor_id,
    )

    assert version.version_number == 3
    assert version.role == "support"
    assert version.snapshot == {"a": 1}
    assert version.created_by_user_id == actor_id
    assert session.added == [version]

    version = _version(tenant_id, agent.id)
    updated = await service.update_agent_version(
        FakeSession(FakeResult(version)),
        tenant_id=tenant_id,
        version_id=version.id,
        values={"tone": "direct", "unknown": "ignored"},
    )
    assert updated.tone == "direct"
    assert not hasattr(updated, "unknown")

    published = await service.publish_agent_version(
        FakeSession(FakeResult(version)),
        tenant_id=tenant_id,
        version_id=version.id,
    )
    assert published.status == "published"
    assert published.is_immutable is True


@pytest.mark.asyncio
async def test_agent_version_lookup_missing_raises() -> None:
    with pytest.raises(service.ProductAgentNotFoundError):
        await service.get_agent_version_for_tenant(
            FakeSession(FakeResult(None)),
            tenant_id=uuid4(),
            version_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_agent_deployment_validates_active_version_owner() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    version = _version(tenant_id, agent.id)

    session = FakeSession(FakeResult(agent), FakeResult(version))
    deployment = await service.create_agent_deployment(
        session,
        tenant_id=tenant_id,
        agent_id=agent.id,
        name="No Send",
        channel="test_lab",
        environment="no_send",
        active_version_id=version.id,
        created_by_user_id=uuid4(),
    )

    assert deployment.active_version_id == version.id
    assert deployment.send_enabled is None or deployment.send_enabled is False
    assert session.added == [deployment]

    wrong_version = _version(tenant_id, uuid4())
    with pytest.raises(service.ProductAgentError):
        await service.create_agent_deployment(
            FakeSession(FakeResult(agent), FakeResult(wrong_version)),
            tenant_id=tenant_id,
            agent_id=agent.id,
            name="No Send",
            channel="test_lab",
            environment="no_send",
            active_version_id=wrong_version.id,
            created_by_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_get_and_transition_deployment() -> None:
    tenant_id = uuid4()
    deployment = _deployment(tenant_id)

    assert await service.get_deployment_for_tenant(
        FakeSession(FakeResult(deployment)),
        tenant_id=tenant_id,
        deployment_id=deployment.id,
    ) is deployment

    session = FakeSession(FakeResult(deployment))
    transitioned = await service.transition_agent_deployment(
        session,
        tenant_id=tenant_id,
        deployment_id=deployment.id,
        to_state="published_no_send",
        actor_user_id=uuid4(),
        reason="test passed",
    )

    assert transitioned.publish_state == "published_no_send"
    assert len(session.added) == 1
    assert session.added[0].from_state == "ready_for_approval"
    assert session.added[0].to_state == "published_no_send"

    with pytest.raises(service.ProductAgentNotFoundError):
        await service.get_deployment_for_tenant(
            FakeSession(FakeResult(None)),
            tenant_id=tenant_id,
            deployment_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_create_tool_action_and_knowledge_bindings() -> None:
    tenant_id = uuid4()
    version = _version(tenant_id)

    tool_session = FakeSession(FakeResult(version))
    tool = await service.create_tool_binding(
        tool_session,
        tenant_id=tenant_id,
        agent_version_id=version.id,
        tool_name="catalog.search",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required=True,
    )
    assert tool.required is True
    assert tool_session.added == [tool]

    action_session = FakeSession(FakeResult(version))
    action = await service.create_action_binding(
        action_session,
        tenant_id=tenant_id,
        agent_version_id=version.id,
        action_key="ticket.create",
        execution_mode="dry_run_only",
        permissions={"ticket": "create"},
        enabled=True,
    )
    assert action.execution_mode == "dry_run_only"
    assert action_session.added == [action]

    source_id = uuid4()
    source_session = FakeSession(FakeResult(version), FakeResult(source_id))
    source_binding = await service.create_knowledge_source_binding(
        source_session,
        tenant_id=tenant_id,
        agent_version_id=version.id,
        knowledge_source_id=source_id,
    )
    assert source_binding.knowledge_source_id == source_id

    with pytest.raises(service.ProductAgentNotFoundError):
        await service.create_knowledge_source_binding(
            FakeSession(FakeResult(version), FakeResult(None)),
            tenant_id=tenant_id,
            agent_version_id=version.id,
            knowledge_source_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_assert_workflow_exists_for_tenant() -> None:
    tenant_id = uuid4()
    workflow_id = uuid4()

    await service.assert_workflow_exists_for_tenant(
        FakeSession(FakeResult(workflow_id)),
        tenant_id=tenant_id,
        workflow_id=workflow_id,
    )
    with pytest.raises(service.ProductAgentNotFoundError):
        await service.assert_workflow_exists_for_tenant(
            FakeSession(FakeResult(None)),
            tenant_id=tenant_id,
            workflow_id=workflow_id,
        )

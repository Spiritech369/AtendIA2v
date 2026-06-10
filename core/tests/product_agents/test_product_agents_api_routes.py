from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from atendia.api import product_agents_routes
from atendia.api._auth_helpers import AuthUser
from atendia.product_agents.schemas import (
    ActionBindingCreate,
    AgentDeploymentCreate,
    AgentDeploymentTransitionRequest,
    AgentVersionCreate,
    AgentVersionUpdate,
    KnowledgeSourceBindingCreate,
    ProductAgentCreate,
    ProductAgentUpdate,
    ToolBindingCreate,
)


class DummySession:
    def __init__(self) -> None:
        self.committed = False
        self.refreshed = []
        self.results = []

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj) -> None:
        self.refreshed.append(obj)

    async def execute(self, _statement):
        return self.results.pop(0)


class DummyScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class DummyResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return DummyScalars(self.values)


def _user(tenant_id):
    return AuthUser(
        user_id=uuid4(),
        tenant_id=tenant_id,
        role="tenant_admin",
        email="admin@example.com",
    )


def _row(tenant_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Support",
        role="custom",
        status="draft",
        tone="calm",
        language="es",
        system_prompt="Help customers.",
        ops_config={"product_first": True},
        created_at=None,
        updated_at=None,
    )


def test_http_error_maps_product_agent_errors() -> None:
    assert product_agents_routes._http_error(
        product_agents_routes.service.ProductAgentNotFoundError("missing")
    ).status_code == 404
    assert product_agents_routes._http_error(
        product_agents_routes.service.ImmutableAgentVersionError("locked")
    ).status_code == 409
    assert product_agents_routes._http_error(
        product_agents_routes.service.PublishStateTransitionError("bad")
    ).status_code == 409
    assert product_agents_routes._http_error(
        product_agents_routes.service.ProductAgentError("invalid")
    ).status_code == 400


@pytest.mark.asyncio
async def test_create_product_agent_route_uses_tenant_scoped_service(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    created = _row(tenant_id)
    calls = {}

    async def fake_create_product_agent(session_arg, **kwargs):
        calls["session"] = session_arg
        calls["kwargs"] = kwargs
        return created

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_product_agent",
        fake_create_product_agent,
    )

    result = await product_agents_routes.create_product_agent(
        ProductAgentCreate(name="Support", tone="calm", instructions="Help customers."),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert result is created
    assert session.committed is True
    assert session.refreshed == [created]
    assert calls["session"] is session
    assert calls["kwargs"]["tenant_id"] == tenant_id
    assert calls["kwargs"]["name"] == "Support"


@pytest.mark.asyncio
async def test_agent_routes_list_get_update_and_errors(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    row = _row(tenant_id)

    async def fake_list_product_agents(session_arg, **kwargs):
        assert session_arg is session
        assert kwargs["tenant_id"] == tenant_id
        return [row]

    async def fake_get_agent_for_tenant(_session, **_kwargs):
        return row

    async def fake_update_product_agent(_session, **kwargs):
        assert kwargs["values"] == {"name": "New"}
        return row

    monkeypatch.setattr(
        product_agents_routes.service,
        "list_product_agents",
        fake_list_product_agents,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "get_agent_for_tenant",
        fake_get_agent_for_tenant,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "update_product_agent",
        fake_update_product_agent,
    )

    assert await product_agents_routes.list_product_agents(
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == [row]
    assert await product_agents_routes.get_product_agent(
        row.id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) is row
    assert await product_agents_routes.update_product_agent(
        row.id,
        ProductAgentUpdate(name="New"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) is row

    async def fake_missing_agent(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("missing")

    monkeypatch.setattr(
        product_agents_routes.service,
        "get_agent_for_tenant",
        fake_missing_agent,
    )
    with pytest.raises(HTTPException) as exc_info:
        await product_agents_routes.get_product_agent(
            row.id,
            tenant_id=tenant_id,
            _user=_user(tenant_id),
            session=session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_version_routes_cover_create_update_publish_and_list(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    agent_id = uuid4()
    version = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        is_immutable=False,
        role=None,
        tone=None,
        language=None,
        instructions=None,
        prompt_blocks=[],
        snapshot={},
        change_summary=None,
        published_at=None,
        created_at=None,
        updated_at=None,
    )
    session.results.append(DummyResult([version]))

    async def fake_get_agent_for_tenant(*_args, **_kwargs):
        return _row(tenant_id)

    async def fake_create_agent_version(_session, **kwargs):
        assert kwargs["created_by_user_id"]
        return version

    async def fake_update_agent_version(_session, **kwargs):
        assert kwargs["values"] == {"tone": "warm"}
        return version

    async def fake_publish_agent_version(_session, **_kwargs):
        return version

    monkeypatch.setattr(
        product_agents_routes.service,
        "get_agent_for_tenant",
        fake_get_agent_for_tenant,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "create_agent_version",
        fake_create_agent_version,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "update_agent_version",
        fake_update_agent_version,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "publish_agent_version",
        fake_publish_agent_version,
    )

    assert await product_agents_routes.list_agent_versions(
        agent_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == [version]
    assert await product_agents_routes.create_agent_version(
        agent_id,
        AgentVersionCreate(role="support"),
        tenant_id=tenant_id,
        user=_user(tenant_id),
        session=session,
    ) is version
    assert await product_agents_routes.update_agent_version(
        version.id,
        AgentVersionUpdate(tone="warm"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) is version
    assert await product_agents_routes.publish_agent_version(
        version.id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) is version


@pytest.mark.asyncio
async def test_transition_deployment_route_stays_in_service_boundary(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    deployment = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        publish_state="published_no_send",
    )
    calls = {}

    async def fake_transition_agent_deployment(session_arg, **kwargs):
        calls["session"] = session_arg
        calls["kwargs"] = kwargs
        return deployment

    monkeypatch.setattr(
        product_agents_routes.service,
        "transition_agent_deployment",
        fake_transition_agent_deployment,
    )

    result = await product_agents_routes.transition_agent_deployment(
        uuid4(),
        AgentDeploymentTransitionRequest(to_state="published_no_send", reason="approved"),
        tenant_id=tenant_id,
        user=_user(tenant_id),
        session=session,
    )

    assert result is deployment
    assert session.committed is True
    assert session.refreshed == [deployment]
    assert calls["session"] is session
    assert calls["kwargs"]["tenant_id"] == tenant_id
    assert calls["kwargs"]["to_state"] == "published_no_send"


@pytest.mark.asyncio
async def test_deployment_routes_cover_list_and_create(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    deployment = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        publish_state="draft",
        created_at=None,
    )
    session.results.append(DummyResult([deployment]))

    async def fake_create_agent_deployment(_session, **kwargs):
        assert kwargs["tenant_id"] == tenant_id
        return deployment

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_agent_deployment",
        fake_create_agent_deployment,
    )

    assert await product_agents_routes.list_agent_deployments(
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == [deployment]
    assert await product_agents_routes.create_agent_deployment(
        AgentDeploymentCreate(agent_id=deployment.agent_id, name="No Send"),
        tenant_id=tenant_id,
        user=_user(tenant_id),
        session=session,
    ) is deployment


@pytest.mark.asyncio
async def test_binding_routes_delegate_to_service(monkeypatch) -> None:
    tenant_id = uuid4()
    version_id = uuid4()
    session = DummySession()
    source_id = uuid4()

    async def fake_create_tool_binding(_session, **kwargs):
        return SimpleNamespace(id=uuid4(), tool_name=kwargs["tool_name"])

    async def fake_create_action_binding(_session, **kwargs):
        return SimpleNamespace(id=uuid4(), action_key=kwargs["action_key"])

    async def fake_create_knowledge_source_binding(_session, **kwargs):
        return SimpleNamespace(id=uuid4(), knowledge_source_id=kwargs["knowledge_source_id"])

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_tool_binding",
        fake_create_tool_binding,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "create_action_binding",
        fake_create_action_binding,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "create_knowledge_source_binding",
        fake_create_knowledge_source_binding,
    )

    tool = await product_agents_routes.create_tool_binding(
        version_id,
        ToolBindingCreate(tool_name="catalog.search"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    action = await product_agents_routes.create_action_binding(
        version_id,
        ActionBindingCreate(action_key="ticket.create"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    source = await product_agents_routes.create_knowledge_source_binding(
        version_id,
        KnowledgeSourceBindingCreate(knowledge_source_id=source_id),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert tool["tool_name"] == "catalog.search"
    assert action["action_key"] == "ticket.create"
    assert source["knowledge_source_id"] == source_id
    assert session.committed is True


@pytest.mark.asyncio
async def test_update_product_agent_route_maps_service_error(monkeypatch) -> None:
    async def fake_update_product_agent(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad update")

    monkeypatch.setattr(
        product_agents_routes.service,
        "update_product_agent",
        fake_update_product_agent,
    )
    with pytest.raises(HTTPException) as exc_info:
        await product_agents_routes.update_product_agent(
            uuid4(),
            ProductAgentUpdate(name="New"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_version_routes_map_service_errors(monkeypatch) -> None:
    async def fake_create_agent_version(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad create")

    async def fake_update_agent_version(*_args, **_kwargs):
        raise product_agents_routes.service.ImmutableAgentVersionError("locked")

    async def fake_publish_agent_version(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad publish")

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_agent_version",
        fake_create_agent_version,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "update_agent_version",
        fake_update_agent_version,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "publish_agent_version",
        fake_publish_agent_version,
    )

    with pytest.raises(HTTPException) as create_exc:
        await product_agents_routes.create_agent_version(
            uuid4(),
            AgentVersionCreate(),
            tenant_id=uuid4(),
            user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as update_exc:
        await product_agents_routes.update_agent_version(
            uuid4(),
            AgentVersionUpdate(tone="warm"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as publish_exc:
        await product_agents_routes.publish_agent_version(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )

    assert create_exc.value.status_code == 400
    assert update_exc.value.status_code == 409
    assert publish_exc.value.status_code == 400


@pytest.mark.asyncio
async def test_deployment_routes_map_service_errors(monkeypatch) -> None:
    async def fake_create_agent_deployment(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad deployment")

    async def fake_transition_agent_deployment(*_args, **_kwargs):
        raise product_agents_routes.service.PublishStateTransitionError("bad state")

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_agent_deployment",
        fake_create_agent_deployment,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "transition_agent_deployment",
        fake_transition_agent_deployment,
    )

    with pytest.raises(HTTPException) as create_exc:
        await product_agents_routes.create_agent_deployment(
            AgentDeploymentCreate(agent_id=uuid4(), name="No Send"),
            tenant_id=uuid4(),
            user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as transition_exc:
        await product_agents_routes.transition_agent_deployment(
            uuid4(),
            AgentDeploymentTransitionRequest(to_state="production"),
            tenant_id=uuid4(),
            user=_user(uuid4()),
            session=DummySession(),
        )

    assert create_exc.value.status_code == 400
    assert transition_exc.value.status_code == 409


@pytest.mark.asyncio
async def test_binding_routes_map_service_errors(monkeypatch) -> None:
    async def fake_create_tool_binding(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad tool")

    async def fake_create_action_binding(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad action")

    async def fake_create_knowledge_source_binding(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("bad source")

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_tool_binding",
        fake_create_tool_binding,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "create_action_binding",
        fake_create_action_binding,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "create_knowledge_source_binding",
        fake_create_knowledge_source_binding,
    )

    with pytest.raises(HTTPException) as tool_exc:
        await product_agents_routes.create_tool_binding(
            uuid4(),
            ToolBindingCreate(tool_name="catalog.search"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as action_exc:
        await product_agents_routes.create_action_binding(
            uuid4(),
            ActionBindingCreate(action_key="ticket.create"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as source_exc:
        await product_agents_routes.create_knowledge_source_binding(
            uuid4(),
            KnowledgeSourceBindingCreate(knowledge_source_id=uuid4()),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )

    assert tool_exc.value.status_code == 400
    assert action_exc.value.status_code == 400
    assert source_exc.value.status_code == 404

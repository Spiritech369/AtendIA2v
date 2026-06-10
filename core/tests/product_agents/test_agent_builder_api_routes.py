from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from atendia.api import product_agents_routes
from atendia.api._auth_helpers import AuthUser
from atendia.product_agents.schemas import (
    AgentActionBindingCreate,
    AgentBuilderConfigUpdate,
    AgentKnowledgeBindingCreate,
    AgentTestRunCreate,
    AgentTestScenarioCreate,
    AgentTestSuiteCreate,
    AgentToolBindingCreate,
    AgentVersionCreate,
)


class DummySession:
    def __init__(self) -> None:
        self.committed = False
        self.refreshed = []

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj) -> None:
        self.refreshed.append(obj)


def _user(tenant_id):
    return AuthUser(
        user_id=uuid4(),
        tenant_id=tenant_id,
        role="tenant_admin",
        email="admin@example.com",
    )


def _version(tenant_id, agent_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        is_immutable=False,
        role="support",
        tone="warm",
        language="es",
        instructions="Use approved sources.",
        prompt_blocks=[],
        snapshot={},
        change_summary=None,
        published_at=None,
        created_at=None,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_builder_options_route_delegates_with_tenant_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    calls = {}

    async def fake_options(session_arg, **kwargs):
        calls["session"] = session_arg
        calls["kwargs"] = kwargs
        return {
            "knowledge_sources": [],
            "tools": [],
            "actions": [],
            "workflows": [],
            "registry_status": {"send": "blocked_for_builder_mvp"},
        }

    monkeypatch.setattr(product_agents_routes.service, "list_builder_options", fake_options)

    result = await product_agents_routes.list_builder_options(
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert result["registry_status"]["send"] == "blocked_for_builder_mvp"
    assert calls == {"session": session, "kwargs": {"tenant_id": tenant_id}}


@pytest.mark.asyncio
async def test_knowledge_source_options_route_delegates_with_tenant_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    calls = {}

    async def fake_options(session_arg, **kwargs):
        calls["session"] = session_arg
        calls["kwargs"] = kwargs
        return []

    monkeypatch.setattr(
        product_agents_routes.service,
        "list_knowledge_source_options",
        fake_options,
    )

    result = await product_agents_routes.list_knowledge_source_options(
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert result == []
    assert calls == {"session": session, "kwargs": {"tenant_id": tenant_id}}


@pytest.mark.asyncio
async def test_tool_and_action_options_routes_delegate_with_tenant_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    session = DummySession()
    calls = []

    async def fake_tool_options(session_arg, **kwargs):
        calls.append(("tools", session_arg, kwargs))
        return [{"key": "catalog.search", "kind": "tool"}]

    async def fake_action_options(session_arg, **kwargs):
        calls.append(("actions", session_arg, kwargs))
        return [{"key": "send_message", "kind": "action"}]

    monkeypatch.setattr(product_agents_routes.service, "list_tool_options", fake_tool_options)
    monkeypatch.setattr(product_agents_routes.service, "list_action_options", fake_action_options)

    tools = await product_agents_routes.list_tool_options(
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    actions = await product_agents_routes.list_action_options(
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert tools == [{"key": "catalog.search", "kind": "tool"}]
    assert actions == [{"key": "send_message", "kind": "action"}]
    assert calls == [
        ("tools", session, {"tenant_id": tenant_id}),
        ("actions", session, {"tenant_id": tenant_id}),
    ]


@pytest.mark.asyncio
async def test_builder_state_route_maps_missing_agent(monkeypatch) -> None:
    async def fake_state(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("missing")

    monkeypatch.setattr(product_agents_routes.service, "get_agent_builder_state", fake_state)

    with pytest.raises(HTTPException) as exc_info:
        await product_agents_routes.get_agent_builder_state(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_agent_knowledge_bindings_routes_use_agent_draft_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    source_id = uuid4()
    binding_id = uuid4()
    session = DummySession()
    calls = []

    async def fake_list(session_arg, **kwargs):
        calls.append(("list", session_arg, kwargs))
        return []

    async def fake_bind(session_arg, **kwargs):
        calls.append(("bind", session_arg, kwargs))
        return {
            "id": binding_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "agent_version_id": uuid4(),
            "knowledge_source_id": source_id,
            "source_name": "Policies",
            "source_type": "document",
            "status": "active",
            "health": "healthy",
            "required": True,
            "binding_mode": "answer_basis",
            "priority": 0,
            "blocker": False,
            "blocker_reason": None,
            "checksum": None,
            "version": None,
            "last_indexed_at": None,
            "error_message": None,
            "metadata": {},
        }

    async def fake_unbind(session_arg, **kwargs):
        calls.append(("unbind", session_arg, kwargs))

    monkeypatch.setattr(product_agents_routes.service, "list_agent_knowledge_bindings", fake_list)
    monkeypatch.setattr(product_agents_routes.service, "bind_agent_knowledge_source", fake_bind)
    monkeypatch.setattr(product_agents_routes.service, "unbind_agent_knowledge_source", fake_unbind)

    assert await product_agents_routes.list_agent_knowledge_bindings(
        agent_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == []
    created = await product_agents_routes.bind_agent_knowledge_source(
        agent_id,
        AgentKnowledgeBindingCreate(knowledge_source_id=source_id),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    deleted = await product_agents_routes.unbind_agent_knowledge_source(
        agent_id,
        binding_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert created["knowledge_source_id"] == source_id
    assert deleted is None
    assert session.committed is True
    assert calls[0] == ("list", session, {"tenant_id": tenant_id, "agent_id": agent_id})
    assert calls[1][2]["knowledge_source_id"] == source_id
    assert calls[2] == (
        "unbind",
        session,
        {"tenant_id": tenant_id, "agent_id": agent_id, "binding_id": binding_id},
    )


@pytest.mark.asyncio
async def test_agent_tool_binding_routes_use_agent_draft_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    binding_id = uuid4()
    session = DummySession()
    calls = []

    async def fake_list(session_arg, **kwargs):
        calls.append(("list", session_arg, kwargs))
        return []

    async def fake_bind(session_arg, **kwargs):
        calls.append(("bind", session_arg, kwargs))
        return {
            "id": binding_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "agent_version_id": uuid4(),
            "tool_name": kwargs["tool_name"],
            "label": "Catalog search",
            "category": "fact_lookup",
            "enabled": kwargs["enabled"],
            "required": kwargs["required"],
            "risk_level": "read_only",
            "side_effect_type": "none",
            "has_side_effects": False,
            "blocker": False,
            "blocker_reason": None,
            "input_schema": {},
            "output_schema": {},
            "metadata": {},
        }

    async def fake_unbind(session_arg, **kwargs):
        calls.append(("unbind", session_arg, kwargs))

    monkeypatch.setattr(product_agents_routes.service, "list_agent_tool_bindings", fake_list)
    monkeypatch.setattr(product_agents_routes.service, "bind_agent_tool", fake_bind)
    monkeypatch.setattr(product_agents_routes.service, "unbind_agent_tool", fake_unbind)

    assert await product_agents_routes.list_agent_tool_bindings(
        agent_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == []
    created = await product_agents_routes.bind_agent_tool(
        agent_id,
        AgentToolBindingCreate(tool_name="catalog.search"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    deleted = await product_agents_routes.unbind_agent_tool(
        agent_id,
        binding_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert created["tool_name"] == "catalog.search"
    assert created["side_effect_type"] == "none"
    assert deleted is None
    assert session.committed is True
    assert calls[0] == ("list", session, {"tenant_id": tenant_id, "agent_id": agent_id})
    assert calls[1][2]["tool_name"] == "catalog.search"
    assert calls[2] == (
        "unbind",
        session,
        {"tenant_id": tenant_id, "agent_id": agent_id, "binding_id": binding_id},
    )


@pytest.mark.asyncio
async def test_agent_action_binding_routes_use_agent_draft_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    binding_id = uuid4()
    session = DummySession()
    calls = []

    async def fake_list(session_arg, **kwargs):
        calls.append(("list", session_arg, kwargs))
        return []

    async def fake_bind(session_arg, **kwargs):
        calls.append(("bind", session_arg, kwargs))
        return {
            "id": binding_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "agent_version_id": uuid4(),
            "action_key": kwargs["action_key"],
            "label": "Trigger workflow",
            "category": "workflow",
            "enabled": kwargs["enabled"],
            "execution_mode": kwargs["execution_mode"],
            "approval_required": True,
            "risk_level": "external_write",
            "side_effect_type": "workflow_trigger",
            "has_side_effects": True,
            "required_auth": False,
            "required_permissions": ["workflow.trigger"],
            "permissions": kwargs["permissions"],
            "blocker": False,
            "blocker_reason": None,
            "publish_blockers": ["workflow_binding_required"],
            "metadata": {},
        }

    async def fake_unbind(session_arg, **kwargs):
        calls.append(("unbind", session_arg, kwargs))

    monkeypatch.setattr(product_agents_routes.service, "list_agent_action_bindings", fake_list)
    monkeypatch.setattr(product_agents_routes.service, "bind_agent_action", fake_bind)
    monkeypatch.setattr(product_agents_routes.service, "unbind_agent_action", fake_unbind)

    assert await product_agents_routes.list_agent_action_bindings(
        agent_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == []
    created = await product_agents_routes.bind_agent_action(
        agent_id,
        AgentActionBindingCreate(action_key="trigger_workflow"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    deleted = await product_agents_routes.unbind_agent_action(
        agent_id,
        binding_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert created["action_key"] == "trigger_workflow"
    assert created["has_side_effects"] is True
    assert deleted is None
    assert session.committed is True
    assert calls[0] == ("list", session, {"tenant_id": tenant_id, "agent_id": agent_id})
    assert calls[1][2]["execution_mode"] == "disabled"
    assert calls[2] == (
        "unbind",
        session,
        {"tenant_id": tenant_id, "agent_id": agent_id, "binding_id": binding_id},
    )


@pytest.mark.asyncio
async def test_agent_readiness_route_uses_agent_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version_id = uuid4()

    async def fake_readiness(_session, **kwargs):
        assert kwargs == {"tenant_id": tenant_id, "agent_id": agent_id}
        return {
            "status": "blocked",
            "version_id": version_id,
            "agent_id": agent_id,
            "checks": [],
            "blocking_codes": [],
            "safety": {},
            "test_lab_passed": False,
            "live_publish_allowed": False,
        }

    monkeypatch.setattr(
        product_agents_routes.service,
        "evaluate_agent_builder_readiness",
        fake_readiness,
    )

    result = await product_agents_routes.get_agent_readiness(
        agent_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=DummySession(),
    )

    assert result["agent_id"] == agent_id
    assert result["live_publish_allowed"] is False


@pytest.mark.asyncio
async def test_agent_knowledge_routes_map_service_errors(monkeypatch) -> None:
    async def fake_error(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("missing")

    monkeypatch.setattr(product_agents_routes.service, "list_agent_knowledge_bindings", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "bind_agent_knowledge_source", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "unbind_agent_knowledge_source", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "list_agent_tool_bindings", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "bind_agent_tool", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "unbind_agent_tool", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "list_agent_action_bindings", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "bind_agent_action", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "unbind_agent_action", fake_error)
    monkeypatch.setattr(
        product_agents_routes.service,
        "evaluate_agent_builder_readiness",
        fake_error,
    )

    with pytest.raises(HTTPException) as list_exc:
        await product_agents_routes.list_agent_knowledge_bindings(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as bind_exc:
        await product_agents_routes.bind_agent_knowledge_source(
            uuid4(),
            AgentKnowledgeBindingCreate(knowledge_source_id=uuid4()),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as unbind_exc:
        await product_agents_routes.unbind_agent_knowledge_source(
            uuid4(),
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as readiness_exc:
        await product_agents_routes.get_agent_readiness(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as tool_list_exc:
        await product_agents_routes.list_agent_tool_bindings(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as tool_bind_exc:
        await product_agents_routes.bind_agent_tool(
            uuid4(),
            AgentToolBindingCreate(tool_name="catalog.search"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as tool_unbind_exc:
        await product_agents_routes.unbind_agent_tool(
            uuid4(),
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as action_list_exc:
        await product_agents_routes.list_agent_action_bindings(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as action_bind_exc:
        await product_agents_routes.bind_agent_action(
            uuid4(),
            AgentActionBindingCreate(action_key="trigger_workflow"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as action_unbind_exc:
        await product_agents_routes.unbind_agent_action(
            uuid4(),
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )

    assert list_exc.value.status_code == 404
    assert bind_exc.value.status_code == 404
    assert unbind_exc.value.status_code == 404
    assert readiness_exc.value.status_code == 404
    assert tool_list_exc.value.status_code == 404
    assert tool_bind_exc.value.status_code == 404
    assert tool_unbind_exc.value.status_code == 404
    assert action_list_exc.value.status_code == 404
    assert action_bind_exc.value.status_code == 404
    assert action_unbind_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_builder_draft_version_commits_without_live_side_effects(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    session = DummySession()
    version = _version(tenant_id, agent_id)
    calls = {}

    async def fake_create(session_arg, **kwargs):
        calls["session"] = session_arg
        calls["kwargs"] = kwargs
        return version

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_builder_draft_version",
        fake_create,
    )

    result = await product_agents_routes.create_agent_builder_draft_version(
        agent_id,
        AgentVersionCreate(role="support"),
        tenant_id=tenant_id,
        user=_user(tenant_id),
        session=session,
    )

    assert result is version
    assert session.committed is True
    assert session.refreshed == [version]
    assert calls["kwargs"]["tenant_id"] == tenant_id
    assert calls["kwargs"]["agent_id"] == agent_id


@pytest.mark.asyncio
async def test_create_builder_draft_version_maps_service_error(monkeypatch) -> None:
    async def fake_create(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentError("bad draft")

    monkeypatch.setattr(
        product_agents_routes.service,
        "create_builder_draft_version",
        fake_create,
    )

    with pytest.raises(HTTPException) as exc_info:
        await product_agents_routes.create_agent_builder_draft_version(
            uuid4(),
            AgentVersionCreate(role="support"),
            tenant_id=uuid4(),
            user=_user(uuid4()),
            session=DummySession(),
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_builder_config_uses_existing_immutability_guard(monkeypatch) -> None:
    async def fake_update(*_args, **_kwargs):
        raise product_agents_routes.service.ImmutableAgentVersionError("locked")

    monkeypatch.setattr(product_agents_routes.service, "update_agent_version", fake_update)

    with pytest.raises(HTTPException) as exc_info:
        await product_agents_routes.update_agent_builder_config(
            uuid4(),
            AgentBuilderConfigUpdate(instructions="Cannot edit published."),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_builder_config_commits_draft(monkeypatch) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    session = DummySession()
    version = _version(tenant_id, agent_id)

    async def fake_update(_session, **kwargs):
        assert kwargs["values"] == {"tone": "natural"}
        return version

    monkeypatch.setattr(product_agents_routes.service, "update_agent_version", fake_update)

    result = await product_agents_routes.update_agent_builder_config(
        version.id,
        AgentBuilderConfigUpdate(tone="natural"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert result is version
    assert session.committed is True
    assert session.refreshed == [version]


@pytest.mark.asyncio
async def test_readiness_route_returns_safety_snapshot(monkeypatch) -> None:
    tenant_id = uuid4()
    version_id = uuid4()

    async def fake_readiness(_session, **kwargs):
        assert kwargs == {"tenant_id": tenant_id, "version_id": version_id}
        return {
            "status": "ready",
            "version_id": version_id,
            "checks": [],
            "blocking_codes": [],
            "safety": {
                "send_enabled": False,
                "outbox_enabled": False,
                "live_send_enabled": False,
            },
        }

    monkeypatch.setattr(
        product_agents_routes.service,
        "evaluate_builder_readiness",
        fake_readiness,
    )

    result = await product_agents_routes.get_agent_builder_readiness(
        version_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=DummySession(),
    )

    assert result["status"] == "ready"
    assert result["safety"]["send_enabled"] is False


@pytest.mark.asyncio
async def test_readiness_route_maps_service_error(monkeypatch) -> None:
    async def fake_readiness(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("missing")

    monkeypatch.setattr(
        product_agents_routes.service,
        "evaluate_builder_readiness",
        fake_readiness,
    )

    with pytest.raises(HTTPException) as exc_info:
        await product_agents_routes.get_agent_builder_readiness(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_test_lab_routes_use_product_first_scope(monkeypatch) -> None:
    tenant_id = uuid4()
    version_id = uuid4()
    suite_id = uuid4()
    scenario_id = uuid4()
    run_id = uuid4()
    session = DummySession()
    calls = []

    async def fake_list_suites(session_arg, **kwargs):
        calls.append(("list_suites", session_arg, kwargs))
        return []

    async def fake_create_suite(session_arg, **kwargs):
        calls.append(("create_suite", session_arg, kwargs))
        return {"id": suite_id, "tenant_id": tenant_id, "agent_version_id": version_id}

    async def fake_list_scenarios(session_arg, **kwargs):
        calls.append(("list_scenarios", session_arg, kwargs))
        return []

    async def fake_create_scenario(session_arg, **kwargs):
        calls.append(("create_scenario", session_arg, kwargs))
        return {"id": scenario_id, "tenant_id": tenant_id, "test_suite_id": suite_id}

    async def fake_run_suite(session_arg, **kwargs):
        calls.append(("run_suite", session_arg, kwargs))
        return {"id": run_id, "tenant_id": tenant_id, "test_suite_id": suite_id}

    async def fake_latest_run(session_arg, **kwargs):
        calls.append(("latest_run", session_arg, kwargs))
        return None

    monkeypatch.setattr(product_agents_routes.service, "list_agent_test_suites", fake_list_suites)
    monkeypatch.setattr(product_agents_routes.service, "create_agent_test_suite", fake_create_suite)
    monkeypatch.setattr(
        product_agents_routes.service,
        "list_agent_test_scenarios",
        fake_list_scenarios,
    )
    monkeypatch.setattr(
        product_agents_routes.service,
        "create_agent_test_scenario",
        fake_create_scenario,
    )
    monkeypatch.setattr(product_agents_routes.test_lab, "run_test_suite", fake_run_suite)
    monkeypatch.setattr(product_agents_routes.service, "get_latest_agent_test_run", fake_latest_run)

    assert await product_agents_routes.list_agent_test_suites(
        version_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == []
    created_suite = await product_agents_routes.create_agent_test_suite(
        version_id,
        AgentTestSuiteCreate(name="Readiness"),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    assert created_suite["id"] == suite_id
    assert session.committed is True
    assert session.refreshed == [created_suite]

    assert await product_agents_routes.list_agent_test_scenarios(
        suite_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    ) == []
    created_scenario = await product_agents_routes.create_agent_test_scenario(
        suite_id,
        AgentTestScenarioCreate(name="Hello", turns=[{"inbound_text": "Hola"}]),
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )
    run = await product_agents_routes.run_agent_test_suite(
        suite_id,
        AgentTestRunCreate(),
        tenant_id=tenant_id,
        user=_user(tenant_id),
        session=session,
    )
    latest = await product_agents_routes.get_latest_agent_test_run(
        suite_id,
        tenant_id=tenant_id,
        _user=_user(tenant_id),
        session=session,
    )

    assert created_scenario["id"] == scenario_id
    assert run["id"] == run_id
    assert latest is None
    assert calls[0] == ("list_suites", session, {"tenant_id": tenant_id, "version_id": version_id})
    assert calls[1][2]["name"] == "Readiness"
    assert calls[3][2]["turns"] == [{"inbound_text": "Hola"}]
    assert calls[4][2]["mode"] == "no_send"


@pytest.mark.asyncio
async def test_test_lab_routes_map_service_errors(monkeypatch) -> None:
    async def fake_error(*_args, **_kwargs):
        raise product_agents_routes.service.ProductAgentNotFoundError("missing")

    monkeypatch.setattr(product_agents_routes.service, "list_agent_test_suites", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "create_agent_test_suite", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "list_agent_test_scenarios", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "create_agent_test_scenario", fake_error)
    monkeypatch.setattr(product_agents_routes.test_lab, "run_test_suite", fake_error)
    monkeypatch.setattr(product_agents_routes.service, "get_latest_agent_test_run", fake_error)

    with pytest.raises(HTTPException) as list_suite_exc:
        await product_agents_routes.list_agent_test_suites(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as create_suite_exc:
        await product_agents_routes.create_agent_test_suite(
            uuid4(),
            AgentTestSuiteCreate(name="Bad"),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as list_scenario_exc:
        await product_agents_routes.list_agent_test_scenarios(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as create_scenario_exc:
        await product_agents_routes.create_agent_test_scenario(
            uuid4(),
            AgentTestScenarioCreate(name="Bad", turns=[{"inbound_text": "Hola"}]),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as run_exc:
        await product_agents_routes.run_agent_test_suite(
            uuid4(),
            AgentTestRunCreate(),
            tenant_id=uuid4(),
            user=_user(uuid4()),
            session=DummySession(),
        )
    with pytest.raises(HTTPException) as latest_exc:
        await product_agents_routes.get_latest_agent_test_run(
            uuid4(),
            tenant_id=uuid4(),
            _user=_user(uuid4()),
            session=DummySession(),
        )

    assert list_suite_exc.value.status_code == 404
    assert create_suite_exc.value.status_code == 404
    assert list_scenario_exc.value.status_code == 404
    assert create_scenario_exc.value.status_code == 404
    assert run_exc.value.status_code == 404
    assert latest_exc.value.status_code == 404

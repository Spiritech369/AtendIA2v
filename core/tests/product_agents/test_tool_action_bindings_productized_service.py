from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.product_agent import AgentActionBinding, AgentToolBinding, AgentVersion
from atendia.product_agents import service
from atendia.product_agents.capability_registry import ProductCapability


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
        self.deleted = []
        self.flush_count = 0

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flush_count += 1


def _agent(tenant_id):
    return Agent(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Builder",
        role="support",
        status="draft",
    )


def _draft(tenant_id, agent_id):
    return AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        is_immutable=False,
        role="support",
        language="es",
        instructions="Use approved sources.",
        knowledge_policy={},
        tool_policy={},
        action_policy={},
        field_policy={},
        workflow_policy={},
    )


@pytest.mark.asyncio
async def test_capability_options_separate_fact_tools_from_side_effect_actions() -> None:
    tenant_id = uuid4()
    tools = await service.list_tool_options(FakeSession(), tenant_id=tenant_id)
    actions = await service.list_action_options(FakeSession(), tenant_id=tenant_id)

    assert {tool["key"] for tool in tools} == {
        "catalog.search",
        "quote.resolve",
        "requirements.lookup",
        "document.check",
    }
    assert all(tool["kind"] == "tool" for tool in tools)
    assert all(tool["side_effect_type"] == "none" for tool in tools)
    assert all(not tool["has_side_effects"] for tool in tools)
    assert {action["key"] for action in actions} >= {
        "update_contact_field",
        "trigger_workflow",
        "call_webhook",
        "send_message",
    }
    assert all(action["kind"] == "action" for action in actions)
    assert any(action["has_side_effects"] for action in actions)


@pytest.mark.asyncio
async def test_bind_list_and_unbind_agent_tool_uses_draft_scope() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    draft = _draft(tenant_id, agent.id)
    session = FakeSession(FakeResult(agent), FakeResult(draft))

    created = await service.bind_agent_tool(
        session,
        tenant_id=tenant_id,
        agent_id=agent.id,
        tool_name="catalog.search",
        enabled=True,
        required=True,
    )

    assert created["agent_id"] == agent.id
    assert created["tool_name"] == "catalog.search"
    assert created["side_effect_type"] == "none"
    assert created["has_side_effects"] is False
    assert session.added[0].agent_version_id == draft.id

    listed = await service.list_agent_tool_bindings(
        FakeSession(FakeResult(agent), FakeResult(draft), FakeResult(values=session.added)),
        tenant_id=tenant_id,
        agent_id=agent.id,
    )
    assert listed[0]["tool_name"] == "catalog.search"

    await service.unbind_agent_tool(
        FakeSession(FakeResult(agent), FakeResult(draft), FakeResult(session.added[0])),
        tenant_id=tenant_id,
        agent_id=agent.id,
        binding_id=session.added[0].id,
    )


@pytest.mark.asyncio
async def test_tool_binding_rejects_action_capability_and_unknown_tool() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()

    with pytest.raises(service.ProductAgentNotFoundError):
        await service.bind_agent_tool(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            tool_name="send_message",
            enabled=True,
            required=False,
        )
    with pytest.raises(service.ProductAgentNotFoundError):
        await service.bind_agent_tool(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            tool_name="dinamo.fake_tool",
            enabled=True,
            required=False,
        )


@pytest.mark.asyncio
async def test_tool_binding_defensively_rejects_side_effect_capability(monkeypatch) -> None:
    tenant_id = uuid4()

    def fake_capability(_key, *, kind):
        assert kind == "tool"
        return ProductCapability(
            key="unsafe.tool",
            label="Unsafe tool",
            kind="tool",
            category="unsafe",
            description="Invalid tool for defense in depth.",
            risk_level="external_write",
            side_effect_type="webhook",
            default_mode="dry_run_only",
        )

    monkeypatch.setattr(service, "_require_capability", fake_capability)

    with pytest.raises(service.ProductAgentError, match="side effects"):
        await service.bind_agent_tool(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=uuid4(),
            tool_name="unsafe.tool",
            enabled=True,
            required=False,
        )


@pytest.mark.asyncio
async def test_unbind_missing_tool_and_action_binding_are_tenant_scoped_errors() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    draft = _draft(tenant_id, agent.id)

    with pytest.raises(service.ProductAgentNotFoundError, match="tool binding"):
        await service.unbind_agent_tool(
            FakeSession(FakeResult(agent), FakeResult(draft), FakeResult(None)),
            tenant_id=tenant_id,
            agent_id=agent.id,
            binding_id=uuid4(),
        )
    with pytest.raises(service.ProductAgentNotFoundError, match="action binding"):
        await service.unbind_agent_action(
            FakeSession(FakeResult(agent), FakeResult(draft), FakeResult(None)),
            tenant_id=tenant_id,
            agent_id=agent.id,
            binding_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_capability_options_require_uuid_tenant_shape() -> None:
    with pytest.raises(service.ProductAgentError, match="UUID"):
        await service.list_tool_options(FakeSession(), tenant_id="tenant-1")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bind_list_and_unbind_agent_action_defaults_disabled_no_live() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    draft = _draft(tenant_id, agent.id)
    session = FakeSession(FakeResult(agent), FakeResult(draft))

    created = await service.bind_agent_action(
        session,
        tenant_id=tenant_id,
        agent_id=agent.id,
        action_key="trigger_workflow",
        enabled=False,
        execution_mode="disabled",
        permissions={},
    )

    assert created["action_key"] == "trigger_workflow"
    assert created["enabled"] is False
    assert created["execution_mode"] == "disabled"
    assert created["has_side_effects"] is True
    assert created["blocker"] is False
    assert session.added[0].agent_version_id == draft.id

    listed = await service.list_agent_action_bindings(
        FakeSession(FakeResult(agent), FakeResult(draft), FakeResult(values=session.added)),
        tenant_id=tenant_id,
        agent_id=agent.id,
    )
    assert listed[0]["side_effect_type"] == "workflow_trigger"

    await service.unbind_agent_action(
        FakeSession(FakeResult(agent), FakeResult(draft), FakeResult(session.added[0])),
        tenant_id=tenant_id,
        agent_id=agent.id,
        binding_id=session.added[0].id,
    )


@pytest.mark.asyncio
async def test_action_binding_blocks_live_modes_and_send_message_enablement() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()

    with pytest.raises(service.ProductAgentError, match="blocked"):
        await service.bind_agent_action(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            action_key="update_contact_field",
            enabled=True,
            execution_mode="live",
            permissions={"contact.write": True},
        )
    with pytest.raises(service.ProductAgentError, match="send_message"):
        await service.bind_agent_action(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            action_key="send_message",
            enabled=True,
            execution_mode="approval_required",
            permissions={"send.message": True, "auth_configured": True},
        )


@pytest.mark.asyncio
async def test_action_binding_requires_permissions_and_auth_for_enabled_actions() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()

    with pytest.raises(service.ProductAgentError, match="permissions"):
        await service.bind_agent_action(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            action_key="update_contact_field",
            enabled=True,
            execution_mode="approval_required",
            permissions={},
        )
    with pytest.raises(service.ProductAgentError, match="auth"):
        await service.bind_agent_action(
            FakeSession(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            action_key="call_webhook",
            enabled=True,
            execution_mode="approval_required",
            permissions={"webhook.call": True},
        )


@pytest.mark.asyncio
async def test_action_binding_rejects_enabled_missing_required_permission() -> None:
    with pytest.raises(service.ProductAgentError, match="required permissions"):
        await service.bind_agent_action(
            FakeSession(),
            tenant_id=uuid4(),
            agent_id=uuid4(),
            action_key="update_contact_field",
            enabled=True,
            execution_mode="approval_required",
            permissions={"other.permission": True},
        )


def test_action_binding_blocker_reports_each_publish_guard() -> None:
    tenant_id = uuid4()
    version_id = uuid4()

    assert (
        service._action_binding_blocker(
            AgentActionBinding(
                tenant_id=tenant_id,
                agent_version_id=version_id,
                action_key="unknown.action",
                enabled=False,
                execution_mode="disabled",
                permissions={},
            )
        )
        == "unknown_action"
    )
    assert (
        service._action_binding_blocker(
            AgentActionBinding(
                tenant_id=tenant_id,
                agent_version_id=version_id,
                action_key="update_contact_field",
                enabled=True,
                execution_mode="live",
                permissions={"contact.write": True},
            )
        )
        == "live_mode_blocked"
    )
    assert (
        service._action_binding_blocker(
            AgentActionBinding(
                tenant_id=tenant_id,
                agent_version_id=version_id,
                action_key="update_contact_field",
                enabled=True,
                execution_mode="disabled",
                permissions={"contact.write": True},
            )
        )
        == "enabled_action_disabled_mode"
    )
    assert (
        service._action_binding_blocker(
            AgentActionBinding(
                tenant_id=tenant_id,
                agent_version_id=version_id,
                action_key="send_message",
                enabled=True,
                execution_mode="approval_required",
                permissions={"send.message": True, "auth_configured": True},
            )
        )
        == "send_message_blocked"
    )
    assert (
        service._action_binding_blocker(
            AgentActionBinding(
                tenant_id=tenant_id,
                agent_version_id=version_id,
                action_key="update_contact_field",
                enabled=True,
                execution_mode="approval_required",
                approval_required=True,
                permissions={"wrong": True},
            )
        )
        == "permissions_required"
    )
    assert (
        service._action_binding_blocker(
            AgentActionBinding(
                tenant_id=tenant_id,
                agent_version_id=version_id,
                action_key="update_contact_field",
                enabled=True,
                execution_mode="approval_required",
                approval_required=False,
                permissions={"contact.write": True},
            )
        )
        == "approval_required"
    )


@pytest.mark.asyncio
async def test_readiness_blocks_unknown_or_unsafe_product_action_bindings() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _draft(tenant_id, agent_id)
    action = AgentActionBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        action_key="call_webhook",
        enabled=True,
        execution_mode="approval_required",
        approval_required=True,
        permissions={"webhook.call": True},
    )
    tool = AgentToolBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        tool_name="catalog.search",
        enabled=True,
        required=False,
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[tool]),
            FakeResult(values=[action]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert "actions_unsafe" in readiness["blocking_codes"]
    actions_check = next(
        check for check in readiness["checks"] if check["code"] == "actions_unsafe"
    )
    assert actions_check["metadata"]["unsafe"] == ["call_webhook"]

from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import (
    AgentActionBinding,
    AgentDeployment,
    AgentFieldPermission,
    AgentKnowledgeSourceBinding,
    AgentTestRun,
    AgentToolBinding,
    AgentVersion,
    AgentWorkflowBinding,
)
from atendia.db.models.workflow import Workflow
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

    def all(self):
        return self._values


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

    async def delete(self, obj):
        self.deleted = obj

    async def flush(self):
        self.flush_count += 1


def _agent(tenant_id):
    return Agent(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Builder",
        role="support",
        tone="warm",
        language="es",
        system_prompt="Use approved sources.",
        status="draft",
    )


def _version(tenant_id, agent_id):
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
    )


def _test_run(
    tenant_id,
    version_id,
    *,
    status="passed",
    decision="TEST_LAB_PASSED",
    execution_mode="runtime_v2_agent_service",
):
    return AgentTestRun(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version_id,
        test_suite_id=uuid4(),
        mode="no_send",
        status=status,
        decision=decision,
        trace_ids=["trace-1"] if status == "passed" else [],
        outbox_audit_result={"status": "pass", "count": 0},
        side_effect_audit_result={"status": "pass", "count": 0},
        coverage_summary={"execution_mode": execution_mode},
    )


@pytest.mark.asyncio
async def test_builder_options_are_tenant_scoped_and_do_not_invent_registries() -> None:
    tenant_id = uuid4()
    source = KnowledgeSource(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Policies",
        type="document",
        content_type="text/plain",
        status="active",
        priority=5,
    )
    workflow = Workflow(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Notify advisor",
        trigger_type="agent_event",
        active=False,
        version=3,
    )

    options = await service.list_builder_options(
        FakeSession(
            FakeResult(values=[source]),
            FakeResult(values=[]),
            FakeResult(values=[workflow]),
        ),
        tenant_id=tenant_id,
    )

    assert options["knowledge_sources"][0]["id"] == str(source.id)
    assert options["workflows"][0]["metadata"]["side_effects_default"] is False
    assert {tool["id"] for tool in options["tools"]} >= {"catalog.search", "quote.resolve"}
    assert {action["id"] for action in options["actions"]} >= {
        "update_contact_field",
        "send_message",
    }
    assert all(option["metadata"]["kind"] == "tool" for option in options["tools"])
    assert all(option["metadata"]["kind"] == "action" for option in options["actions"])
    assert all(option["metadata"]["side_effect_type"] == "none" for option in options["tools"])
    assert options["registry_status"]["send"] == "blocked_for_builder_mvp"


@pytest.mark.asyncio
async def test_builder_state_returns_draft_and_published_versions_for_tenant() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    draft = _version(tenant_id, agent.id)
    published = _version(tenant_id, agent.id)
    published.status = "published"
    deployment = AgentDeployment(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent.id,
        active_version_id=published.id,
        name="No send",
    )

    state = await service.get_agent_builder_state(
        FakeSession(
            FakeResult(agent),
            FakeResult(values=[draft, published]),
            FakeResult(values=[deployment]),
        ),
        tenant_id=tenant_id,
        agent_id=agent.id,
    )

    assert state["agent"] is agent
    assert state["draft_version"] is draft
    assert state["published_version"] is published
    assert state["deployments"] == [deployment]


@pytest.mark.asyncio
async def test_create_builder_draft_version_seeds_from_agent_without_live_flags() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    session = FakeSession(FakeResult(agent), FakeResult(agent), FakeResult(0))

    version = await service.create_builder_draft_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent.id,
        payload={},
        created_by_user_id=uuid4(),
    )

    assert version.agent_id == agent.id
    assert version.role == agent.role
    assert version.instructions == agent.system_prompt
    assert version.snapshot == {"builder_source": "product_first_builder"}
    assert session.added == [version]


@pytest.mark.asyncio
async def test_builder_readiness_blocks_missing_required_bindings_and_live_flags() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    version.knowledge_policy = {"requires_knowledge": True}
    version.tool_policy = {"required_tools": ["knowledge.search"]}
    deployment = AgentDeployment(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        active_version_id=version.id,
        name="Unsafe",
        send_enabled=True,
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[deployment]),
            FakeResult(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["status"] == "blocked"
    assert readiness["blocking_codes"] == [
        "required_knowledge_missing",
        "required_tools_missing",
        "live_flags_enabled",
    ]
    assert readiness["safety"]["send_enabled"] is False


@pytest.mark.asyncio
async def test_builder_readiness_blocks_incomplete_identity() -> None:
    tenant_id = uuid4()
    version = AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        version_number=1,
        status="draft",
        is_immutable=False,
        role=None,
        language=None,
        instructions=None,
        knowledge_policy={},
        tool_policy={},
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["blocking_codes"] == ["identity_incomplete", "required_knowledge_missing"]
    identity_check = readiness["checks"][0]
    assert identity_check["metadata"]["missing"] == ["role", "language", "instructions"]


@pytest.mark.asyncio
async def test_builder_readiness_reports_ready_when_bindings_are_safe() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    knowledge = AgentKnowledgeSourceBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        knowledge_source_id=uuid4(),
        required=True,
    )
    source = KnowledgeSource(
        id=knowledge.knowledge_source_id,
        tenant_id=tenant_id,
        name="Policies",
        type="document",
        content_type="text/plain",
        status="active",
    )
    tool = AgentToolBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        tool_name="catalog.search",
        enabled=True,
        required=True,
    )
    action = AgentActionBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        action_key="update_contact_field",
        enabled=True,
        execution_mode="approval_required",
        approval_required=True,
        permissions={"contact.write": True},
    )
    field = AgentFieldPermission(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        field_key="customer_name",
        can_write=True,
        evidence_required=True,
    )
    workflow = AgentWorkflowBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        workflow_id=uuid4(),
        event_type="agent_event",
        enabled=True,
        execution_mode="dry_run_only",
        side_effects_allowed=False,
        customer_visible_output_allowed=False,
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[knowledge]),
            FakeResult(values=[tool]),
            FakeResult(values=[action]),
            FakeResult(values=[field]),
            FakeResult(values=[workflow]),
            FakeResult(values=[]),
            FakeResult(values=[source]),
            FakeResult(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["status"] == "ready"
    assert readiness["blocking_codes"] == []
    assert {check["status"] for check in readiness["checks"]} == {"pass", "warn"}


@pytest.mark.asyncio
async def test_builder_readiness_marks_test_lab_passed_when_latest_run_passed() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    knowledge = AgentKnowledgeSourceBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        knowledge_source_id=uuid4(),
        required=True,
    )
    source = KnowledgeSource(
        id=knowledge.knowledge_source_id,
        tenant_id=tenant_id,
        name="Policies",
        type="document",
        content_type="text/plain",
        status="active",
    )
    run = _test_run(tenant_id, version.id)

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[knowledge]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[source]),
            FakeResult(run),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["test_lab_passed"] is True
    assert "test_lab_passed" in {check["code"] for check in readiness["checks"]}
    assert readiness["live_publish_allowed"] is False


@pytest.mark.asyncio
async def test_builder_readiness_blocks_publish_when_latest_test_lab_failed() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    failed_run = _test_run(tenant_id, version.id, status="failed", decision="TEST_LAB_FAILED")

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(failed_run),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert "test_lab_failed" in readiness["blocking_codes"]
    assert readiness["test_lab_passed"] is False
    assert readiness["live_publish_allowed"] is False


@pytest.mark.asyncio
async def test_test_lab_real_mode_updates_readiness_only_on_pass() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    blocked_run = _test_run(
        tenant_id,
        version.id,
        status="blocked",
        decision="REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API",
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(blocked_run),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["test_lab_passed"] is False
    assert "test_lab_failed" in readiness["blocking_codes"]
    assert readiness["live_publish_allowed"] is False


@pytest.mark.asyncio
async def test_openai_direct_provider_cannot_mark_builder_readiness() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    direct_run = _test_run(
        tenant_id,
        version.id,
        execution_mode="openai_direct_provider",
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(direct_run),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["test_lab_passed"] is False
    assert "test_lab_runtime_v2_required" in readiness["blocking_codes"]
    assert readiness["live_publish_allowed"] is False


@pytest.mark.asyncio
async def test_builder_readiness_blocks_unsafe_fields_actions_and_workflows() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version = _version(tenant_id, agent_id)
    action = AgentActionBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        action_key="ticket.create",
        enabled=True,
        execution_mode="dry_run_only",
        permissions={},
    )
    field = AgentFieldPermission(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        field_key="credit_status",
        can_write=True,
        evidence_required=False,
    )
    workflow = AgentWorkflowBinding(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        workflow_id=uuid4(),
        event_type="agent_event",
        enabled=True,
        execution_mode="dry_run_only",
        side_effects_allowed=True,
        customer_visible_output_allowed=True,
    )

    readiness = await service.evaluate_builder_readiness(
        FakeSession(
            FakeResult(version),
            FakeResult(values=[]),
            FakeResult(values=[]),
            FakeResult(values=[action]),
            FakeResult(values=[field]),
            FakeResult(values=[workflow]),
            FakeResult(values=[]),
            FakeResult(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert "actions_unsafe" in readiness["blocking_codes"]
    assert "field_policy_unsafe" in readiness["blocking_codes"]
    assert "workflow_bindings_unsafe" in readiness["blocking_codes"]

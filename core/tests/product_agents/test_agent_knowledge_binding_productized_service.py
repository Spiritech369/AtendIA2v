from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import AgentKnowledgeSourceBinding, AgentVersion
from atendia.product_agents import service


class ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class Result:
    def __init__(self, scalar=None, values=None, rows=None):
        self._scalar = scalar
        self._values = values or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return ScalarResult(self._values)

    def all(self):
        return self._rows


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.deleted = []
        self.flush_count = 0

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flush_count += 1


def _agent(tenant_id, agent_id):
    return Agent(
        id=agent_id,
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
    )


def _source(tenant_id, source_id, *, status="active", metadata=None):
    return KnowledgeSource(
        id=source_id,
        tenant_id=tenant_id,
        name="Policies",
        type="document",
        content_type="text/plain",
        status=status,
        metadata_json=metadata or {},
    )


@pytest.mark.asyncio
async def test_agent_knowledge_binding_productized_list_bind_and_unbind() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    source_id = uuid4()
    draft = _draft(tenant_id, agent_id)
    source = _source(tenant_id, source_id, metadata={"health": "failed", "error_message": "raw"})
    binding = AgentKnowledgeSourceBinding(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=draft.id,
        knowledge_source_id=source_id,
        required=True,
        binding_mode="answer_basis",
        priority=7,
    )
    session = Session(
        Result(_agent(tenant_id, agent_id)),
        Result(draft),
        Result(rows=[(binding, source)]),
        Result(_agent(tenant_id, agent_id)),
        Result(draft),
        Result(source),
        Result(_agent(tenant_id, agent_id)),
        Result(draft),
        Result(binding),
    )

    bindings = await service.list_agent_knowledge_bindings(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    created = await service.bind_agent_knowledge_source(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        knowledge_source_id=source_id,
        binding_mode="answer_basis",
        required=True,
        priority=7,
    )
    await service.unbind_agent_knowledge_source(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        binding_id=binding.id,
    )

    assert bindings[0]["error_message"] == "Error redacted. See source trace."
    assert created["metadata"]["source_health_at_binding"] == "unhealthy"
    assert session.added[0].knowledge_source_id == source_id
    assert session.deleted == [binding]
    assert session.flush_count == 2


@pytest.mark.asyncio
async def test_agent_knowledge_binding_productized_blocks_bad_source_and_missing_draft() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    source_id = uuid4()
    draft = _draft(tenant_id, agent_id)

    with pytest.raises(service.ProductAgentError):
        await service.bind_agent_knowledge_source(
            Session(
                Result(_agent(tenant_id, agent_id)),
                Result(draft),
                Result(_source(tenant_id, source_id, status="deleted")),
            ),
            tenant_id=tenant_id,
            agent_id=agent_id,
            knowledge_source_id=source_id,
            binding_mode="answer_basis",
            required=True,
            priority=0,
        )

    with pytest.raises(service.ProductAgentNotFoundError):
        await service.get_draft_version_for_agent(
            Session(Result(_agent(tenant_id, agent_id)), Result()),
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

    with pytest.raises(service.ProductAgentNotFoundError):
        await service.unbind_agent_knowledge_source(
            Session(Result(_agent(tenant_id, agent_id)), Result(draft), Result()),
            tenant_id=tenant_id,
            agent_id=agent_id,
            binding_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_agent_builder_readiness_agent_scope_and_missing_bound_source() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    draft = _draft(tenant_id, agent_id)
    draft.role = "support"
    draft.language = "es"
    draft.instructions = "Use tenant sources."
    draft.knowledge_policy = {}
    draft.tool_policy = {}
    binding = AgentKnowledgeSourceBinding(
        tenant_id=tenant_id,
        agent_version_id=draft.id,
        knowledge_source_id=uuid4(),
        required=True,
    )

    readiness = await service.evaluate_agent_builder_readiness(
        Session(
            Result(_agent(tenant_id, agent_id)),
            Result(draft),
            Result(draft),
            Result(values=[binding]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(None),
        ),
        tenant_id=tenant_id,
        agent_id=agent_id,
    )

    assert readiness["agent_id"] == agent_id
    assert "knowledge_sources_healthy" in readiness["blocking_codes"]
    knowledge_check = next(
        item for item in readiness["checks"] if item["code"] == "knowledge_sources_healthy"
    )
    assert knowledge_check["metadata"]["unhealthy"][0]["reason"] == "source_missing"


def test_product_agent_source_health_pending_and_redacted_error() -> None:
    source = _source(
        uuid4(),
        uuid4(),
        status="parsing",
        metadata={"error_message_redacted": "Safe error"},
    )

    option = service._source_option(source, [])

    assert option["health"] == "pending"
    assert option["blocker_reason"] == "source_not_indexed"
    assert option["error_message"] == "Safe error"

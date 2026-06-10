from uuid import uuid4

import pytest

from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import AgentKnowledgeSourceBinding, AgentVersion
from atendia.product_agents import service


class ScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class Result:
    def __init__(self, scalar=None, values=None):
        self._scalar = scalar
        self._values = values or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return ScalarResult(self._values)


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_agent_readiness_passes_knowledge_connected_not_publish() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    source_id = uuid4()
    version = AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        is_immutable=False,
        role="support",
        language="es",
        instructions="Use tenant sources.",
        knowledge_policy={},
        tool_policy={},
    )
    binding = AgentKnowledgeSourceBinding(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        knowledge_source_id=source_id,
        required=True,
    )
    source = KnowledgeSource(
        id=source_id,
        tenant_id=tenant_id,
        name="Policies",
        type="document",
        content_type="text/plain",
        status="indexed",
    )

    readiness = await service.evaluate_builder_readiness(
        Session(
            Result(version),
            Result(values=[binding]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[source]),
            Result(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["status"] == "ready"
    assert readiness["blocking_codes"] == []
    assert readiness["test_lab_passed"] is False
    assert readiness["live_publish_allowed"] is False
    assert readiness["safety"]["send_enabled"] is False

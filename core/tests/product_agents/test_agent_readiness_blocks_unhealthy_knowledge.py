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
async def test_agent_readiness_blocks_unhealthy_knowledge() -> None:
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
        name="Broken FAQ",
        type="faq",
        content_type="faq",
        status="failed",
        metadata_json={"error_message_redacted": "Parser failed"},
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

    assert readiness["status"] == "blocked"
    assert "knowledge_sources_healthy" in readiness["blocking_codes"]
    check = next(
        item for item in readiness["checks"] if item["code"] == "knowledge_sources_healthy"
    )
    assert check["message"] == "Esta fuente no esta lista para publicar."
    assert check["metadata"]["unhealthy"][0]["reason"] == "source_unhealthy"

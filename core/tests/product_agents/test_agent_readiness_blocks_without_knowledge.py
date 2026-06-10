from uuid import uuid4

import pytest

from atendia.db.models.product_agent import AgentVersion
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


def _version(tenant_id):
    return AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        version_number=1,
        status="draft",
        is_immutable=False,
        role="support",
        language="es",
        instructions="Use tenant sources.",
        knowledge_policy={},
        tool_policy={},
    )


@pytest.mark.asyncio
async def test_agent_readiness_blocks_without_knowledge() -> None:
    tenant_id = uuid4()
    version = _version(tenant_id)

    readiness = await service.evaluate_builder_readiness(
        Session(
            Result(version),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(values=[]),
            Result(None),
        ),
        tenant_id=tenant_id,
        version_id=version.id,
    )

    assert readiness["status"] == "blocked"
    assert "required_knowledge_missing" in readiness["blocking_codes"]
    assert readiness["test_lab_passed"] is False
    assert readiness["live_publish_allowed"] is False

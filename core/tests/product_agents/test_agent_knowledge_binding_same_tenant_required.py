from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.product_agent import AgentVersion
from atendia.product_agents import service


class Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


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


@pytest.mark.asyncio
async def test_agent_knowledge_binding_same_tenant_required() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    source_id = uuid4()

    with pytest.raises(service.ProductAgentNotFoundError):
        await service.bind_agent_knowledge_source(
            Session(
                Result(_agent(tenant_id, agent_id)),
                Result(_draft(tenant_id, agent_id)),
                Result(),
            ),
            tenant_id=tenant_id,
            agent_id=agent_id,
            knowledge_source_id=source_id,
            binding_mode="answer_basis",
            required=True,
            priority=0,
        )

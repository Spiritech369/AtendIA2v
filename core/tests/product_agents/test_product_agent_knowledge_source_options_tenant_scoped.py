from uuid import uuid4

import pytest

from atendia.db.models.knowledge_os import KnowledgeSource
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

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_product_agent_knowledge_source_options_tenant_scoped() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    source = KnowledgeSource(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Policies",
        type="document",
        content_type="text/plain",
        status="active",
        priority=0,
        metadata_json={
            "checksum": "sha256:abc",
            "last_indexed_at": "2026-06-07T00:00:00Z",
        },
    )

    options = await service.list_knowledge_source_options(
        Session(Result(values=[source]), Result(rows=[(source.id, agent_id)])),
        tenant_id=tenant_id,
    )

    assert options == [
        {
            "id": source.id,
            "tenant_id": tenant_id,
            "name": "Policies",
            "source_type": "document",
            "content_type": "text/plain",
            "status": "active",
            "health": "healthy",
            "parser_status": None,
            "index_status": None,
            "checksum": "sha256:abc",
            "version": None,
            "last_indexed_at": "2026-06-07T00:00:00Z",
            "error_message": None,
            "bound_agent_ids": [agent_id],
            "blocker": False,
            "blocker_reason": None,
            "metadata": {"priority": 0, "owner": None},
        }
    ]

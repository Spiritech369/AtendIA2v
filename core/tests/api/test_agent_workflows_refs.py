"""W5 — reverse dependency: which workflows reference this agent.

GET /api/v1/agents/{agent_id}/workflows scans tenant workflow
definitions for assign_agent nodes pointing at the agent.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_agent(tenant_id: str) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                aid = (
                    await conn.execute(
                        text("INSERT INTO agents (tenant_id, name) VALUES (:t, :n) RETURNING id"),
                        {"t": tenant_id, "n": f"agent_{uuid4().hex[:6]}"},
                    )
                ).scalar()
                return str(aid)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def _make_workflow(client, name: str, definition: dict) -> str:
    resp = client.post(
        "/api/v1/workflows",
        json={
            "name": name,
            "trigger_type": "message_received",
            "definition": definition,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _def_with_agent(agent_id: str) -> dict:
    return {
        "nodes": [
            {"id": "trigger_1", "type": "trigger", "config": {"event": "message_received"}},
            {"id": "assign_1", "type": "assign_agent", "config": {"agent_id": agent_id}},
        ],
        "edges": [{"from": "trigger_1", "to": "assign_1"}],
    }


def test_lists_workflows_that_reference_the_agent(client_tenant_admin) -> None:
    agent_id = _seed_agent(client_tenant_admin.tenant_id)
    wf_ref = _make_workflow(client_tenant_admin, "uses-agent", _def_with_agent(agent_id))
    _make_workflow(
        client_tenant_admin,
        "no-agent",
        {
            "nodes": [
                {"id": "trigger_1", "type": "trigger", "config": {"event": "message_received"}}
            ],
            "edges": [],
        },
    )

    resp = client_tenant_admin.get(f"/api/v1/agents/{agent_id}/workflows")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = {w["id"] for w in data}
    assert wf_ref in ids
    referenced = next(w for w in data if w["id"] == wf_ref)
    assert referenced["name"] == "uses-agent"
    assert "assign_1" in referenced["node_ids"]
    # the workflow that doesn't touch the agent must not appear
    assert len(ids) == 1


def test_unknown_agent_404(client_tenant_admin) -> None:
    resp = client_tenant_admin.get(f"/api/v1/agents/{uuid4()}/workflows")
    assert resp.status_code == 404


def test_requires_auth(client) -> None:
    resp = client.get(f"/api/v1/agents/{uuid4()}/workflows")
    assert resp.status_code in (401, 403)

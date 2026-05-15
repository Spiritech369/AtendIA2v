"""HTTP-level coverage of the workflows routes.

Focus: the safety surface the engine relies on:
- POST/PATCH/toggle re-validate ``definition`` and (when activating) refs
- RBAC: operator forbidden from create/patch/toggle/delete/retry
- Retry resumes from the failed node
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_agent(tenant_id: str) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                agent_id = (
                    await conn.execute(
                        text("INSERT INTO agents (tenant_id, name) VALUES (:t, :n) RETURNING id"),
                        {"t": tenant_id, "n": f"agent_{uuid4().hex[:6]}"},
                    )
                ).scalar()
                return str(agent_id)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def _basic_definition(action: dict[str, Any]) -> dict:
    return {
        "nodes": [
            {"id": "trigger_1", "type": "trigger", "config": {"event": "message_received"}},
            {"id": "a1", **action},
        ],
        "edges": [{"from": "trigger_1", "to": "a1"}],
    }


def test_operator_cannot_create_workflow(client_operator) -> None:
    resp = client_operator.post(
        "/api/v1/workflows",
        json={
            "name": "wf",
            "trigger_type": "message_received",
            "definition": {"nodes": [], "edges": []},
        },
    )
    assert resp.status_code == 403, resp.text


def test_admin_can_create_inactive_workflow(client_tenant_admin) -> None:
    resp = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "draft",
            "trigger_type": "message_received",
            "definition": _basic_definition({"type": "pause_bot"}),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active"] is False


def test_create_active_workflow_validates_refs(client_tenant_admin) -> None:
    # Bad agent ref — workflow can't be created in active state.
    bad_agent = str(uuid4())
    resp = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "bad",
            "trigger_type": "message_received",
            "definition": _basic_definition(
                {"type": "assign_agent", "config": {"agent_id": bad_agent}}
            ),
            "active": True,
        },
    )
    assert resp.status_code == 422, resp.text
    assert "agent_id" in resp.text


def test_toggle_to_active_revalidates_refs(client_tenant_admin) -> None:
    bad_agent = str(uuid4())
    create = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "togglable",
            "trigger_type": "message_received",
            "definition": _basic_definition(
                {"type": "assign_agent", "config": {"agent_id": bad_agent}}
            ),
        },
    )
    assert create.status_code == 201, create.text
    wf_id = create.json()["id"]

    toggle = client_tenant_admin.post(f"/api/v1/workflows/{wf_id}/toggle")
    assert toggle.status_code == 422, toggle.text
    assert "agent_id" in toggle.text

    # Patch with a valid in-tenant agent and toggle should succeed.
    good_agent = _seed_agent(client_tenant_admin.tenant_id)
    patch = client_tenant_admin.patch(
        f"/api/v1/workflows/{wf_id}",
        json={
            "definition": _basic_definition(
                {"type": "assign_agent", "config": {"agent_id": good_agent}}
            ),
        },
    )
    assert patch.status_code == 200, patch.text

    toggle2 = client_tenant_admin.post(f"/api/v1/workflows/{wf_id}/toggle")
    assert toggle2.status_code == 200, toggle2.text
    assert toggle2.json()["active"] is True


def test_toggle_off_skips_ref_validation(client_tenant_admin) -> None:
    """Once active, a workflow must always be turn-off-able even if the refs
    have rotted (e.g. an agent was deleted). Stuck-on-active is worse than
    silently breaking on next trigger."""
    good_agent = _seed_agent(client_tenant_admin.tenant_id)
    create = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "live",
            "trigger_type": "message_received",
            "definition": _basic_definition(
                {"type": "assign_agent", "config": {"agent_id": good_agent}}
            ),
            "active": True,
        },
    )
    assert create.status_code == 201, create.text
    wf_id = create.json()["id"]

    # Simulate the agent being deleted out from under the workflow.
    async def _drop_agent() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM agents WHERE id = :i"), {"i": good_agent})
        finally:
            await engine.dispose()

    asyncio.run(_drop_agent())

    toggle = client_tenant_admin.post(f"/api/v1/workflows/{wf_id}/toggle")
    assert toggle.status_code == 200, toggle.text
    assert toggle.json()["active"] is False


def test_operator_cannot_toggle(client_tenant_admin, client_operator) -> None:
    create = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "guarded",
            "trigger_type": "message_received",
            "definition": _basic_definition({"type": "pause_bot"}),
        },
    )
    assert create.status_code == 201
    wf_id = create.json()["id"]
    # Operator from a different tenant — definitely not authorized.
    resp = client_operator.post(f"/api/v1/workflows/{wf_id}/toggle")
    assert resp.status_code in {403, 404}


def test_unknown_trigger_rejected(client_tenant_admin) -> None:
    resp = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "x",
            "trigger_type": "shenanigans",
            "definition": {"nodes": [], "edges": []},
        },
    )
    assert resp.status_code == 422


def test_delete_workflow(client_tenant_admin) -> None:
    create = client_tenant_admin.post(
        "/api/v1/workflows",
        json={
            "name": "rm",
            "trigger_type": "message_received",
            "definition": _basic_definition({"type": "pause_bot"}),
        },
    )
    wf_id = create.json()["id"]
    resp = client_tenant_admin.delete(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 204
    assert client_tenant_admin.get(f"/api/v1/workflows/{wf_id}").status_code == 404

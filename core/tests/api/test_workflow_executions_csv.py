"""W16 — workflow execution log CSV export.

GET /api/v1/workflows/{workflow_id}/executions.csv streams the real
execution rows (tenant-scoped via the workflow) as a CSV attachment.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_execution(workflow_id: str, status: str, error: str | None = None) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                eid = (
                    await conn.execute(
                        text(
                            "INSERT INTO workflow_executions "
                            "(id, workflow_id, status, started_at, finished_at, "
                            " current_node_id, error) "
                            "VALUES (:i, :w, :s, now(), now(), :n, :e) RETURNING id"
                        ),
                        {
                            "i": str(uuid4()),
                            "w": workflow_id,
                            "s": status,
                            "n": "node_a",
                            "e": error,
                        },
                    )
                ).scalar()
                return str(eid)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def _make_workflow(client) -> str:
    resp = client.post(
        "/api/v1/workflows",
        json={
            "name": f"wf_{uuid4().hex[:6]}",
            "trigger_type": "message_received",
            "definition": {"nodes": [], "edges": []},
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def test_executions_csv_streams_rows(client_tenant_admin) -> None:
    wf_id = _make_workflow(client_tenant_admin)
    eid_ok = _seed_execution(wf_id, "completed")
    eid_fail = _seed_execution(wf_id, "failed", error="boom")

    resp = client_tenant_admin.get(f"/api/v1/workflows/{wf_id}/executions.csv")

    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers.get("content-disposition", "")
    body = resp.text
    # header row
    assert "execution_id" in body
    assert "status" in body
    # both rows present, with the failure reason
    assert eid_ok in body
    assert eid_fail in body
    assert "completed" in body
    assert "failed" in body
    assert "boom" in body


def test_executions_csv_unknown_workflow_404(client_tenant_admin) -> None:
    resp = client_tenant_admin.get(f"/api/v1/workflows/{uuid4()}/executions.csv")
    assert resp.status_code == 404


def test_executions_csv_requires_auth(client) -> None:
    resp = client.get(f"/api/v1/workflows/{uuid4()}/executions.csv")
    assert resp.status_code in (401, 403)

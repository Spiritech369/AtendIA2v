"""Sprint B.3 — /knowledge/audit-logs + /knowledge/conflicts read from the DB.

Before this change:
* /audit-logs returned an empty list for every non-demo tenant —
  it did not query the events table where admin.kb.* actions land.
* /conflicts returned `items=[]` for non-demo with a COUNT-only total,
  ignoring kb_conflicts rows the tenant might already have.

These tests pin the new contract: when DB content exists, both
endpoints surface it for non-demo tenants; tenant isolation is
enforced; the empty-state still works.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_admin_kb_event(
    tenant_id: str, action: str, payload: dict, actor_user_id: str | None = None
) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO events "
                        "(id, tenant_id, type, payload, occurred_at, actor_user_id) "
                        "VALUES (:id, :t, :ty, CAST(:p AS jsonb), :o, :u)"
                    ),
                    {
                        "id": str(uuid4()),
                        "t": tenant_id,
                        "ty": f"admin.{action}",
                        "p": json.dumps(payload),
                        "o": datetime.now(UTC),
                        "u": actor_user_id,
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(_do())


def _seed_kb_conflict(tenant_id: str, title: str, severity: str = "high") -> str:
    cid = str(uuid4())

    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO kb_conflicts "
                        "(id, tenant_id, title, detection_type, severity, status, "
                        " entity_a_type, entity_a_id, entity_b_type, entity_b_id) "
                        "VALUES (:i, :t, :tl, 'semantic_overlap', :sv, 'open', "
                        " 'faq', :a, 'faq', :b)"
                    ),
                    {
                        "i": cid,
                        "t": tenant_id,
                        "tl": title,
                        "sv": severity,
                        "a": str(uuid4()),
                        "b": str(uuid4()),
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(_do())
    return cid


def test_audit_logs_non_demo_returns_kb_admin_events(client_tenant_admin) -> None:
    """A kb.document.uploaded event in the events table must surface in
    the /audit-logs response for the tenant that owns it."""
    marker = f"FILE_{uuid4().hex[:6]}.pdf"
    _seed_admin_kb_event(
        client_tenant_admin.tenant_id,
        action="kb.document.uploaded",
        payload={"filename": marker, "document_id": str(uuid4())},
    )
    resp = client_tenant_admin.get("/api/v1/knowledge/audit-logs")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items, "expected at least one audit log entry for the seeded event"
    matched = [i for i in items if marker in i["target"] or marker in i["action"]]
    assert matched, f"expected an item citing {marker}, got: {items}"
    # The action should expose the kb.* suffix without the admin. prefix —
    # the prefix is an internal taxonomy detail, not for the operator UI.
    assert matched[0]["action"].startswith("kb.")


def test_audit_logs_non_demo_does_not_leak_other_tenants_events(
    client_tenant_admin, superadmin_seed
) -> None:
    other_tid = superadmin_seed[0]
    leak_marker = f"FOREIGN_FILE_{uuid4().hex[:6]}.pdf"
    _seed_admin_kb_event(
        other_tid,
        action="kb.document.uploaded",
        payload={"filename": leak_marker, "document_id": str(uuid4())},
    )
    resp = client_tenant_admin.get("/api/v1/knowledge/audit-logs")
    assert resp.status_code == 200, resp.text
    body_text = resp.text
    assert leak_marker not in body_text, (
        f"event from tenant {other_tid} leaked into tenant "
        f"{client_tenant_admin.tenant_id}'s audit-logs"
    )


def test_audit_logs_non_demo_empty_when_no_events(client_operator) -> None:
    resp = client_operator.get("/api/v1/knowledge/audit-logs")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


def test_conflicts_non_demo_returns_real_rows(client_tenant_admin) -> None:
    title = f"Conflicto de prueba {uuid4().hex[:6]}"
    cid = _seed_kb_conflict(client_tenant_admin.tenant_id, title=title, severity="high")
    resp = client_tenant_admin.get("/api/v1/knowledge/conflicts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    matched = [i for i in body["items"] if i["id"] == cid]
    assert matched, f"expected a conflict with id {cid}, got: {body['items']}"
    assert matched[0]["title"] == title
    assert matched[0]["severity"] == "high"


def test_conflicts_non_demo_does_not_leak_other_tenants(
    client_tenant_admin, superadmin_seed
) -> None:
    other_tid = superadmin_seed[0]
    leak_title = f"OTRO_TENANT_{uuid4().hex[:6]}"
    foreign_cid = _seed_kb_conflict(other_tid, title=leak_title)
    resp = client_tenant_admin.get("/api/v1/knowledge/conflicts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert all(i["id"] != foreign_cid for i in body["items"]), (
        f"conflict {foreign_cid} from tenant {other_tid} leaked into tenant "
        f"{client_tenant_admin.tenant_id}"
    )
    assert leak_title not in resp.text


def test_conflicts_non_demo_empty_when_no_rows(client_operator) -> None:
    resp = client_operator.get("/api/v1/knowledge/conflicts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0

"""C9 — per-message edit + soft delete.

PATCH /api/v1/conversations/{cid}/messages/{mid}  -> edit text
DELETE /api/v1/conversations/{cid}/messages/{mid} -> soft delete
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conv_with_message(tid: str, body: str = "hola") -> tuple[str, str]:
    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164) "
                            "VALUES (:t, :p) RETURNING id"
                        ),
                        {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id) "
                            "VALUES (:t, :c) RETURNING id"
                        ),
                        {"t": tid, "c": cust},
                    )
                ).scalar()
                msg = (
                    await conn.execute(
                        text(
                            "INSERT INTO messages "
                            "(id, conversation_id, tenant_id, direction, text, sent_at) "
                            "VALUES (:i, :cv, :t, 'outbound', :x, now()) RETURNING id"
                        ),
                        {"i": str(uuid4()), "cv": conv, "t": tid, "x": body},
                    )
                ).scalar()
                return str(conv), str(msg)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def test_edit_message_updates_text_and_marks_edited(client_tenant_admin) -> None:
    conv, msg = _seed_conv_with_message(client_tenant_admin.tenant_id, "viejo")

    resp = client_tenant_admin.patch(
        f"/api/v1/conversations/{conv}/messages/{msg}",
        json={"text": "texto corregido"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "texto corregido"
    assert body["edited_at"] is not None

    listing = client_tenant_admin.get(f"/api/v1/conversations/{conv}/messages")
    assert listing.status_code == 200
    items = listing.json()["items"]
    edited = next(m for m in items if m["id"] == msg)
    assert edited["text"] == "texto corregido"
    assert edited["edited_at"] is not None


def test_delete_message_soft_deletes_and_hides_from_list(client_tenant_admin) -> None:
    conv, msg = _seed_conv_with_message(client_tenant_admin.tenant_id)

    resp = client_tenant_admin.delete(f"/api/v1/conversations/{conv}/messages/{msg}")
    assert resp.status_code in (200, 204), resp.text

    listing = client_tenant_admin.get(f"/api/v1/conversations/{conv}/messages")
    ids = {m["id"] for m in listing.json()["items"]}
    assert msg not in ids


def test_edit_unknown_message_404(client_tenant_admin) -> None:
    conv, _ = _seed_conv_with_message(client_tenant_admin.tenant_id)
    resp = client_tenant_admin.patch(
        f"/api/v1/conversations/{conv}/messages/{uuid4()}",
        json={"text": "x"},
    )
    assert resp.status_code == 404


def test_edit_rejects_empty_text(client_tenant_admin) -> None:
    conv, msg = _seed_conv_with_message(client_tenant_admin.tenant_id)
    resp = client_tenant_admin.patch(
        f"/api/v1/conversations/{conv}/messages/{msg}",
        json={"text": "   "},
    )
    assert resp.status_code == 422


def test_message_edit_requires_auth(client) -> None:
    resp = client.patch(
        f"/api/v1/conversations/{uuid4()}/messages/{uuid4()}",
        json={"text": "x"},
    )
    assert resp.status_code in (401, 403)

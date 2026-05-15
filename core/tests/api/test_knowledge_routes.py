"""HTTP-level tests for /api/v1/knowledge.

Focus: the safety surface of session 2 — RBAC, cross-tenant 404s, the
new download/retry routes, the reindex cooldown, and the test-endpoint
rate limit. The Redis-backed limits are flushed between tests so we don't
poison sibling cases.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from uuid import uuid4

import pytest
import redis.asyncio as redis_async

from atendia.config import get_settings

PDF_HEADER = b"%PDF-1.7\n%minimal\n"


def _flush_kb_limits() -> None:
    async def _do() -> None:
        client = redis_async.Redis.from_url(get_settings().redis_url)
        try:
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match="kb:*", count=200)
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
        finally:
            await client.aclose()

    asyncio.run(_do())


@pytest.fixture(autouse=True)
def _isolate_kb_limits() -> None:
    _flush_kb_limits()
    yield
    _flush_kb_limits()


def _upload_pdf(client, name: str = "doc.pdf") -> dict:
    files = {"file": (name, BytesIO(PDF_HEADER), "application/pdf")}
    resp = client.post("/api/v1/knowledge/documents/upload", files=files)
    assert resp.status_code == 202, resp.text
    return resp.json()


def test_operator_cannot_upload(client_operator) -> None:
    files = {"file": ("d.pdf", BytesIO(PDF_HEADER), "application/pdf")}
    resp = client_operator.post("/api/v1/knowledge/documents/upload", files=files)
    assert resp.status_code == 403, resp.text


def test_admin_uploads_and_downloads_pdf(client_tenant_admin) -> None:
    doc = _upload_pdf(client_tenant_admin)
    download = client_tenant_admin.get(
        f"/api/v1/knowledge/documents/{doc['id']}/download",
    )
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.content == PDF_HEADER


def test_upload_rejects_mismatched_magic_bytes(client_tenant_admin) -> None:
    files = {"file": ("trojan.pdf", BytesIO(b"GIF89a not a pdf"), "application/pdf")}
    resp = client_tenant_admin.post(
        "/api/v1/knowledge/documents/upload",
        files=files,
    )
    assert resp.status_code == 400
    assert "do not match" in resp.text.lower()


def test_download_404_cross_tenant(client_tenant_admin) -> None:
    # A random UUID — not owned by this tenant.
    resp = client_tenant_admin.get(
        f"/api/v1/knowledge/documents/{uuid4()}/download",
    )
    assert resp.status_code == 404


def test_retry_rejects_processing_status(client_tenant_admin) -> None:
    doc = _upload_pdf(client_tenant_admin)
    # Fresh upload starts in 'processing' — retry should refuse.
    resp = client_tenant_admin.post(
        f"/api/v1/knowledge/documents/{doc['id']}/retry",
    )
    assert resp.status_code == 409


def test_retry_after_error_state_works(client_tenant_admin) -> None:
    doc = _upload_pdf(client_tenant_admin)

    # Force the row into the 'error' state directly via DB.
    async def _to_error() -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE knowledge_documents "
                    "SET status='error', error_message='boom' WHERE id=:i"
                ),
                {"i": doc["id"]},
            )
        await engine.dispose()

    asyncio.run(_to_error())

    resp = client_tenant_admin.post(
        f"/api/v1/knowledge/documents/{doc['id']}/retry",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processing"
    assert body["error_message"] is None


def test_operator_cannot_retry(client_tenant_admin, client_operator) -> None:
    doc = _upload_pdf(client_tenant_admin)
    resp = client_operator.post(
        f"/api/v1/knowledge/documents/{doc['id']}/retry",
    )
    assert resp.status_code in {403, 404}


def test_test_endpoint_rate_limit(client_operator) -> None:
    # 11th call within the window must be 429 (limit is 10).
    last = None
    for _ in range(11):
        last = client_operator.post(
            "/api/v1/knowledge/test",
            json={"query": "hola"},
        )
    assert last is not None
    assert last.status_code == 429, last.text


def test_reindex_cooldown(client_tenant_admin) -> None:
    first = client_tenant_admin.post("/api/v1/knowledge/reindex")
    assert first.status_code == 200
    second = client_tenant_admin.post("/api/v1/knowledge/reindex")
    assert second.status_code == 429


def test_delete_document_db_first(client_tenant_admin) -> None:
    doc = _upload_pdf(client_tenant_admin)
    resp = client_tenant_admin.delete(
        f"/api/v1/knowledge/documents/{doc['id']}",
    )
    assert resp.status_code == 204
    assert (
        client_tenant_admin.get(
            f"/api/v1/knowledge/documents/{doc['id']}",
        ).status_code
        == 404
    )

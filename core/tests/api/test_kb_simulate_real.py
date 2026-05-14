"""Sprint A.4 — /knowledge/simulate returns real KB content for non-demo tenants.

Before this fix, /simulate for non-demo always returned the
``"sources_only"`` empty-state stub regardless of whether the tenant
had FAQs / catalog / document chunks. The operator could not test
their knowledge base via the cockpit, only via the separate
``/knowledge/test`` endpoint.

These tests pin the new contract:
* Empty tenant → keeps the no-KB stub.
* Tenant with a FAQ that lexically matches the query → returns at
  least one ``RetrievedChunk`` with the FAQ's question/answer in the
  preview.
* Tenant with a catalog item that lexically matches the query →
  returns at least one chunk citing the catalog item.
* Cross-tenant isolation: a FAQ owned by tenant B never appears in
  tenant A's simulate response.

ILIKE-based search (no embeddings) keeps these tests deterministic and
offline-friendly; the embedding path is exercised by
``/knowledge/test``'s own coverage.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_faq(tenant_id: str, question: str, answer: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenant_faqs (tenant_id, question, answer) VALUES (:t, :q, :a)"
                    ),
                    {"t": tenant_id, "q": question, "a": answer},
                )
        finally:
            await engine.dispose()

    asyncio.run(_do())


def _seed_catalog(tenant_id: str, name: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) "
                        "VALUES (:t, :s, :n, CAST('{}' AS jsonb))"
                    ),
                    {"t": tenant_id, "s": f"SKU-{uuid4().hex[:8]}", "n": name},
                )
        finally:
            await engine.dispose()

    asyncio.run(_do())


def test_simulate_non_demo_with_matching_faq_returns_real_chunk(
    client_tenant_admin,
) -> None:
    marker = f"PRECIOTEST{uuid4().hex[:6]}"
    _seed_faq(
        client_tenant_admin.tenant_id,
        question=f"Cuanto cuesta {marker}",
        answer=f"El precio listado es {marker}.",
    )
    resp = client_tenant_admin.post(
        "/api/v1/knowledge/simulate",
        json={"message": f"cuanto cuesta {marker}", "agent": "sales", "model": "gpt-4o-mini"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Must NOT be the empty-state stub.
    assert body["retrieved_chunks"], (
        f"expected at least one chunk for a query that matches a seeded FAQ, got: {body}"
    )
    # The seeded answer must be reflected in one of the chunks.
    assert any(marker in c["preview"] for c in body["retrieved_chunks"])
    # mode must be one of the supported literals
    assert body["mode"] in {"llm", "sources_only"}


def test_simulate_non_demo_with_matching_catalog_returns_real_chunk(
    client_tenant_admin,
) -> None:
    marker = f"PRODUCTO_TEST_{uuid4().hex[:6]}"
    _seed_catalog(client_tenant_admin.tenant_id, name=marker)
    resp = client_tenant_admin.post(
        "/api/v1/knowledge/simulate",
        json={"message": marker, "agent": "sales", "model": "gpt-4o-mini"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["retrieved_chunks"], (
        f"expected at least one chunk citing the seeded catalog item, got: {body}"
    )
    assert any(marker in c["preview"] for c in body["retrieved_chunks"])


def test_simulate_non_demo_empty_tenant_keeps_no_kb_stub(client_operator) -> None:
    """A fresh tenant with zero FAQs / chunks / catalog still returns the
    helpful empty-state stub, not an empty list with no guidance."""
    resp = client_operator.post(
        "/api/v1/knowledge/simulate",
        json={"message": "test query", "agent": "sales", "model": "gpt-4o-mini"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "sources_only"
    assert body["retrieved_chunks"] == []
    assert "Carga FAQs" in body["answer"]


def test_simulate_non_demo_isolates_tenants(
    client_tenant_admin,
    superadmin_seed,
) -> None:
    """A FAQ owned by tenant B must never appear in tenant A's simulate
    response. Tenant isolation pin: the only filter that prevents leakage
    is the WHERE tenant_id clause in the FAQ/chunk queries."""
    other_tid = superadmin_seed[0]
    leak_marker = f"FAQ_DE_OTRO_TENANT_{uuid4().hex[:6]}"
    _seed_faq(
        other_tid,
        question=f"¿pregunta privada de B {leak_marker}?",
        answer=f"respuesta privada {leak_marker}",
    )
    # Query with a substring of the leak_marker so we don't echo the marker
    # back via user_message — the leak we care about is on the RETRIEVAL side
    # (FAQ contents reaching the chunks list), not the echo back.
    query_substring = leak_marker.replace("FAQ_DE_", "")
    resp = client_tenant_admin.post(
        "/api/v1/knowledge/simulate",
        json={
            "message": f"buscando algo con {query_substring}",
            "agent": "sales",
            "model": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for chunk in body["retrieved_chunks"]:
        assert leak_marker not in chunk["preview"], (
            f"FAQ from tenant {other_tid} leaked into tenant "
            f"{client_tenant_admin.tenant_id}'s simulate response: {chunk}"
        )

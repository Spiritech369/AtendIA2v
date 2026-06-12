"""T10 — Tests for the real-data `quote()` function (Phase 3c.1).

`quote()` looks up a single catalog SKU and returns a `Quote` (with full
prices + planes + ficha técnica) or `ToolNoDataResult` if the SKU is
missing or inactive. Hits the real Postgres + tenant_catalogs table.

Each test seeds its own tenant + catalog row with `INSERT` and rolls back
via the autouse `db_session` fixture's session.rollback() in conftest.
"""

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.tools.base import Quote, ToolNoDataResult
from atendia.tools.quote import quote

pytestmark = pytest.mark.asyncio


async def test_quote_returns_quote_for_existing_sku(db_session) -> None:
    """Active SKU with full attrs → Quote with all money + JSONB fields."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t10_quote_ok') RETURNING id")
        )
    ).scalar()
    sku = "adventure-150-cc"
    await db_session.execute(
        text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), true)
    """),
        {
            "t": tid,
            "s": sku,
            "n": "Adventure 150 CC",
            "c": "Motoneta",
            "a": json.dumps(
                {
                    "alias": ["adventure", "elite"],
                    "ficha_tecnica": {"motor_cc": 150, "transmision": "automatica"},
                    "precio_lista": "31395",
                    "precio_contado": "29900",
                    "planes_credito": {
                        "plan_10": {"enganche": 3140, "pago_quincenal": 1247, "quincenas": 72},
                    },
                }
            ),
        },
    )
    await db_session.commit()
    try:
        result = await quote(session=db_session, tenant_id=tid, sku=sku)
        assert isinstance(result, Quote)
        assert result.status == "ok"
        assert result.sku == sku
        assert result.name == "Adventure 150 CC"
        assert result.category == "Motoneta"
        assert result.price_lista_mxn == Decimal("31395")
        assert result.price_contado_mxn == Decimal("29900")
        assert result.planes_credito["plan_10"]["enganche"] == 3140
        assert result.ficha_tecnica["motor_cc"] == 150
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_quote_returns_no_data_for_missing_sku(db_session) -> None:
    """SKU not in catalog → ToolNoDataResult with sku-mentioning hint."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t10_quote_missing') RETURNING id")
        )
    ).scalar()
    await db_session.commit()
    try:
        result = await quote(session=db_session, tenant_id=tid, sku="lambretta-200")
        assert isinstance(result, ToolNoDataResult)
        assert result.status == "no_data"
        assert "lambretta-200" in result.hint
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_quote_ignores_inactive_items(db_session) -> None:
    """Inactive SKU is treated identically to a missing SKU."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t10_quote_inactive') RETURNING id")
        )
    ).scalar()
    sku = "discontinued-100"
    await db_session.execute(
        text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), false)
    """),
        {"t": tid, "s": sku, "n": "Discontinued", "c": "Motoneta", "a": "{}"},
    )
    await db_session.commit()
    try:
        result = await quote(session=db_session, tenant_id=tid, sku=sku)
        assert isinstance(result, ToolNoDataResult)
        assert result.status == "no_data"
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_quote_handles_missing_attrs_keys(db_session) -> None:
    """If `attrs` is missing precio_*/planes/ficha keys, falls back to defaults
    rather than crashing — useful during partial ingestion."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t10_quote_partial') RETURNING id")
        )
    ).scalar()
    sku = "minimal-sku"
    await db_session.execute(
        text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active)
        VALUES (:t, :s, :n, :c, CAST(:a AS jsonb), true)
    """),
        {"t": tid, "s": sku, "n": "Minimal", "c": "Otro", "a": "{}"},
    )
    await db_session.commit()
    try:
        result = await quote(session=db_session, tenant_id=tid, sku=sku)
        assert isinstance(result, Quote)
        assert result.price_lista_mxn == Decimal("0")
        assert result.price_contado_mxn == Decimal("0")
        assert result.planes_credito == {}
        assert result.ficha_tecnica == {}
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()


async def test_quote_published_catalog_miss_falls_back_to_approved_tenant_catalog(
    db_session,
) -> None:
    """Published catalog no-match can use an approved tenant source as fallback."""
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t10_approved_fallback') RETURNING id")
        )
    ).scalar()
    catalog_id = uuid4()
    version_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO catalogs (id, tenant_id, name, vertical, status)
            VALUES (:catalog_id, :t, 'Published no match', 'motorcycles', 'active')
            """),
        {"catalog_id": catalog_id, "t": tid},
    )
    await db_session.execute(
        text("""
            INSERT INTO catalog_versions (
                id, tenant_id, catalog_id, version_number, status, snapshot_json
            )
            VALUES (
                :version_id,
                :t,
                :catalog_id,
                1,
                'published',
                CAST(:snapshot AS jsonb)
            )
            """),
        {
            "version_id": version_id,
            "t": tid,
            "catalog_id": catalog_id,
            "snapshot": '{"items":[{"sku":"other","name":"Other","status":"active"}]}',
        },
    )
    await db_session.execute(
        text("UPDATE catalogs SET active_version_id = :version_id WHERE id = :catalog_id"),
        {"version_id": version_id, "catalog_id": catalog_id},
    )
    await db_session.execute(
        text("""
        INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, active, status)
        VALUES (:t, :sku, :name, 'Motoneta', CAST(:attrs AS jsonb), true, 'published')
        """),
        {
            "t": tid,
            "sku": "adventure_elite_150_cc",
            "name": "Adventure Elite 150 CC",
            "attrs": json.dumps(
                {
                    "alias": ["adventure", "adventure elite"],
                    "precio_lista": "31395",
                    "precio_contado": "29900",
                    "planes_credito": {
                        "10%": {
                            "enganche_mxn": 3140,
                            "pago_quincenal_mxn": 1247,
                            "numero_quincenas": 72,
                        },
                    },
                    "catalog_source": {
                        "runtime_status": "approved",
                        "source_id": "approved_catalog",
                    },
                }
            ),
        },
    )
    await db_session.commit()
    try:
        result = await quote(
            session=db_session,
            tenant_id=tid,
            sku="adventure_elite_150_cc",
            plan_code="10%",
        )
        assert isinstance(result, Quote)
        assert result.sku == "adventure_elite_150_cc"
        assert result.cash_price_mxn == Decimal("29900")
        assert result.payment_options["10%"]["enganche_mxn"] == 3140
        assert result.source["catalog_source"] == "tenant_catalogs_approved_fallback"
        assert result.source["source_id"] == "approved_catalog"
    finally:
        await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
        await db_session.commit()

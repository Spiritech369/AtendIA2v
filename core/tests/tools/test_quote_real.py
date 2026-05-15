"""T10 — Tests for the real-data `quote()` function (Phase 3c.1).

`quote()` looks up a single catalog SKU and returns a `Quote` (with full
prices + planes + ficha técnica) or `ToolNoDataResult` if the SKU is
missing or inactive. Hits the real Postgres + tenant_catalogs table.

Each test seeds its own tenant + catalog row with `INSERT` and rolls back
via the autouse `db_session` fixture's session.rollback() in conftest.
"""

import json
from decimal import Decimal

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

"""apply_ai_extractions integration tests against real DB.

Seeds a tenant + customer with known attrs, calls the service with a
synthetic NLU output, and verifies the resulting customer.attrs and
field_suggestions rows.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.contracts.conversation_state import ExtractedField
from atendia.runner.ai_extraction_service import apply_ai_extractions


def _seed_tenant_customer(initial_attrs: dict | None = None) -> tuple[str, str, str]:
    """Return (tenant_id, customer_id, conversation_id)."""

    async def _do() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"aiext_{uuid4().hex[:8]}"},
                )
            ).scalar()
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, attrs) "
                        "VALUES (:t, :p, CAST(:a AS jsonb)) RETURNING id"
                    ),
                    {
                        "t": tid,
                        "p": f"+521555{uuid4().hex[:8]}",
                        "a": json.dumps(initial_attrs or {}),
                    },
                )
            ).scalar()
            conv_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, status, current_stage) "
                        "VALUES (:t, :c, 'active', 'new') RETURNING id"
                    ),
                    {"t": tid, "c": cust_id},
                )
            ).scalar()
        await engine.dispose()
        return str(tid), str(cust_id), str(conv_id)

    return asyncio.run(_do())


def _cleanup(tenant_id: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        await engine.dispose()

    asyncio.run(_do())


def _read_attrs(customer_id: str) -> dict:
    async def _do() -> dict:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT attrs FROM customers WHERE id = :c"),
                    {"c": customer_id},
                )
            ).scalar_one()
        await engine.dispose()
        return row or {}

    return asyncio.run(_do())


def _read_suggestions(customer_id: str) -> list[dict]:
    async def _do() -> list[dict]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT key, suggested_value, confidence, status, evidence_text "
                        "FROM field_suggestions WHERE customer_id = :c "
                        "ORDER BY key"
                    ),
                    {"c": customer_id},
                )
            ).fetchall()
        await engine.dispose()
        return [dict(r._mapping) for r in rows]

    return asyncio.run(_do())


@pytest.fixture
def fresh_seed() -> Iterator[tuple[str, str, str]]:
    tid, cid, conv = _seed_tenant_customer()
    yield tid, cid, conv
    _cleanup(tid)


@pytest.fixture
def seed_with_attrs() -> Iterator[tuple[str, str, str]]:
    tid, cid, conv = _seed_tenant_customer({"plan_credito": "10", "marca": "Honda"})
    yield tid, cid, conv
    _cleanup(tid)


async def _run(
    tenant_id: str,
    customer_id: str,
    conv_id: str,
    entities: dict,
    *,
    turn: int = 1,
    inbound_text: str | None = None,
) -> list:
    engine = create_async_engine(get_settings().database_url)
    SessionMaker = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionMaker() as session:
        applied = await apply_ai_extractions(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            turn_number=turn,
            entities=entities,
            inbound_text=inbound_text,
        )
        await session.commit()
    await engine.dispose()
    return applied


def test_auto_applies_to_empty_attrs(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.95, source_turn=1),
        "plan": ExtractedField(value="10", confidence=0.90, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))

    attrs = _read_attrs(cid)
    assert attrs["marca"] == "Honda"
    assert attrs["plan_credito"] == "10"

    sugg = _read_suggestions(cid)
    assert sugg == []  # no suggestions, all auto


def test_creates_suggestions_for_medium_confidence(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "model": ExtractedField(value="Civic", confidence=0.70, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities, inbound_text="creo que el Civic"))

    attrs = _read_attrs(cid)
    assert "modelo_interes" not in attrs

    sugg = _read_suggestions(cid)
    assert len(sugg) == 1
    assert sugg[0]["key"] == "modelo_interes"
    assert sugg[0]["suggested_value"] == "Civic"
    assert sugg[0]["status"] == "pending"
    assert sugg[0]["evidence_text"] == "creo que el Civic"


def test_creates_suggestion_on_overwrite_even_with_high_confidence(seed_with_attrs):
    """Don't silently change a value the operator already had."""
    tid, cid, conv = seed_with_attrs
    entities = {
        "brand": ExtractedField(value="Yamaha", confidence=0.98, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))

    attrs = _read_attrs(cid)
    assert attrs["marca"] == "Honda"  # unchanged

    sugg = _read_suggestions(cid)
    assert len(sugg) == 1
    assert sugg[0]["suggested_value"] == "Yamaha"
    assert sugg[0]["status"] == "pending"


def test_skips_low_confidence(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.30, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))
    assert _read_attrs(cid) == {}
    assert _read_suggestions(cid) == []


def test_noop_when_value_already_matches(seed_with_attrs):
    tid, cid, conv = seed_with_attrs
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.95, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))
    assert _read_attrs(cid)["marca"] == "Honda"
    assert _read_suggestions(cid) == []


def test_ignores_unknown_entities(fresh_seed):
    tid, cid, conv = fresh_seed
    entities = {
        "weird_thing": ExtractedField(value="abc", confidence=0.99, source_turn=1),
    }
    asyncio.run(_run(tid, cid, conv, entities))
    assert _read_attrs(cid) == {}
    assert _read_suggestions(cid) == []


def test_returns_applied_changes_for_auto_writes(fresh_seed):
    """The returned list drives FIELD_UPDATED system events; SUGGEST and
    SKIP paths must NOT appear there — only AUTO writes that actually
    landed on customer.attrs."""
    tid, cid, conv = fresh_seed
    entities = {
        "brand": ExtractedField(value="Honda", confidence=0.95, source_turn=1),  # AUTO
        "model": ExtractedField(value="Civic", confidence=0.70, source_turn=1),  # SUGGEST
        "city": ExtractedField(value="GDL", confidence=0.30, source_turn=1),  # SKIP
    }
    applied = asyncio.run(_run(tid, cid, conv, entities))

    # Only AUTO ends up in the returned list.
    assert [c.attr_key for c in applied] == ["marca"]
    assert applied[0].old_value is None
    assert applied[0].new_value == "Honda"
    assert applied[0].confidence == pytest.approx(0.95)


def test_returns_empty_when_no_auto_changes(seed_with_attrs):
    """NOOP (same value) + SUGGEST (different value, lower conf) must
    both yield zero AppliedFieldChange entries — neither modifies attrs."""
    tid, cid, conv = seed_with_attrs
    entities = {
        # NOOP — marca already 'Honda'
        "brand": ExtractedField(value="Honda", confidence=0.95, source_turn=1),
        # SUGGEST — plan_credito already '10', new value differs
        "plan": ExtractedField(value="15", confidence=0.95, source_turn=1),
    }
    applied = asyncio.run(_run(tid, cid, conv, entities))
    assert applied == []

"""C2 — Runner persists composer_provider + inbound_text_cleaned on
every turn_traces row. Frontend reads these to render provider badge
+ side-by-side cleaned text in the story."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest.fixture
def fresh_tenant() -> tuple[str, str, str]:
    """Tenant + customer + conversation, cleaned up after."""

    async def _seed() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"c2_runner_test_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'C2 Test') RETURNING id"
                        ),
                        {"t": tid, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
            from atendia.state_machine.default_pipeline import ensure_default_pipeline

            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as s:
                await ensure_default_pipeline(s, tid)
                await s.commit()
            async with engine.begin() as conn:
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                            "VALUES (:t, :c, 'nuevo') RETURNING id"
                        ),
                        {"t": tid, "c": cid},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv},
                )
            return str(tid), str(cid), str(conv)
        finally:
            await engine.dispose()

    async def _cleanup(tid: str) -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await engine.dispose()

    tid, cid, conv = asyncio.run(_seed())
    yield tid, cid, conv
    asyncio.run(_cleanup(tid))


async def test_runner_persists_composer_provider_and_cleaned_text(fresh_tenant):
    """A single run_turn against a fresh tenant lands a turn_traces
    row with composer_provider set ('canned' by default in tests) and
    inbound_text_cleaned set to the normalized text."""
    tid, _cid, conv = fresh_tenant
    from atendia.contracts.message import Message, MessageDirection
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.webhooks.meta_routes import build_composer, build_nlu

    s = get_settings()
    engine = create_async_engine(s.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            nlu = build_nlu(s)
            comp = build_composer(s)
            runner = ConversationRunner(session, nlu, comp)
            inbound = Message(
                id=str(uuid4()),
                conversation_id=conv,
                tenant_id=tid,
                direction=MessageDirection.INBOUND,
                text="¡HOLA! quiero info",  # has caps + accent → cleaning visible
                sent_at=datetime.now(UTC),
                attachments=[],
            )
            await runner.run_turn(
                conversation_id=UUID(conv),
                tenant_id=UUID(tid),
                inbound=inbound,
                turn_number=1,
                arq_pool=None,
                to_phone_e164="+5215999111222",
            )
            await session.commit()

        async with engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT composer_provider, inbound_text_cleaned, inbound_text "
                            "FROM turn_traces WHERE conversation_id = :c "
                            "ORDER BY turn_number ASC LIMIT 1"
                        ),
                        {"c": conv},
                    )
                )
                .mappings()
                .one()
            )

        assert row["composer_provider"] in ("openai", "canned", "fallback"), (
            f"composer_provider must be one of the 3 enum values, got {row['composer_provider']!r}"
        )
        assert row["inbound_text_cleaned"] is not None, (
            "inbound_text_cleaned must be persisted (not NULL)"
        )
        # The cleaned text should differ from the raw text since the raw
        # had caps + accent.
        assert row["inbound_text_cleaned"] != row["inbound_text"], (
            "cleaning must alter the text (lowercase + diacritic strip)"
        )
        assert row["inbound_text_cleaned"] == row["inbound_text_cleaned"].lower()
    finally:
        await engine.dispose()


def test_composer_provider_short_name_classifies_canned():
    from atendia.runner.composer_canned import CannedComposer
    from atendia.runner.conversation_runner import _composer_provider_short_name

    assert _composer_provider_short_name(CannedComposer()) == "canned"


def test_composer_provider_short_name_classifies_openai_success():
    from atendia.runner.composer_openai import OpenAIComposer
    from atendia.runner.conversation_runner import _composer_provider_short_name

    c = OpenAIComposer(api_key="dummy")
    assert _composer_provider_short_name(c) == "openai"
    assert _composer_provider_short_name(c, fallback_used=False) == "openai"


def test_composer_provider_short_name_classifies_openai_fallback():
    from atendia.runner.composer_openai import OpenAIComposer
    from atendia.runner.conversation_runner import _composer_provider_short_name

    c = OpenAIComposer(api_key="dummy")
    assert _composer_provider_short_name(c, fallback_used=True) == "fallback"


def test_composer_provider_short_name_returns_none_for_unknown():
    """Unknown composer class returns None (never ''). The CHECK
    constraint on turn_traces.composer_provider rejects ''."""
    from atendia.runner.conversation_runner import _composer_provider_short_name

    class _MysteryComposer:
        pass

    result = _composer_provider_short_name(_MysteryComposer())
    assert result is None
    assert result != ""  # explicit — CHECK constraint would reject ''

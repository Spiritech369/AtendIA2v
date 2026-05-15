"""D6 Task 2 — when the composer returns suggested_handoff set to a
HandoffReason value, the runner persists a human_handoffs row with
that reason and pauses the bot. The composed messages still go out
(the prompt's holding response) before the pause."""

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
    """Tenant + customer + conversation with default pipeline, cleaned up after."""

    async def _seed() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"d6_handoff_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'D6 Test') RETURNING id"
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


async def test_suggested_handoff_persists_handoff_and_pauses_bot(fresh_tenant):
    """A composer that returns suggested_handoff='obstacle_no_solution'
    must result in:
      * a human_handoffs row with reason='obstacle_no_solution'
      * conversation_state.bot_paused = True
    """
    tid, _cid, conv = fresh_tenant
    from atendia.contracts.message import Message, MessageDirection
    from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.webhooks.meta_routes import build_nlu

    s = get_settings()

    # A stub composer that always returns a holding message + the
    # escalation hint. Mirrors what gpt-4o would do when prompted.
    class _EscalatingComposer:
        async def compose(self, *, input: ComposerInput):
            return (
                ComposerOutput(
                    messages=["Un momento, te conecto con un asesor."],
                    suggested_handoff="obstacle_no_solution",
                ),
                None,  # no UsageMetadata
            )

    engine = create_async_engine(s.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            nlu = build_nlu(s)
            runner = ConversationRunner(session, nlu, _EscalatingComposer())
            inbound = Message(
                id=str(uuid4()),
                conversation_id=conv,
                tenant_id=tid,
                direction=MessageDirection.INBOUND,
                text="esto no me sirve, ya intenté de todo",
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
            handoff = (
                (
                    await conn.execute(
                        text(
                            "SELECT reason, status FROM human_handoffs "
                            "WHERE conversation_id = :c ORDER BY requested_at DESC LIMIT 1"
                        ),
                        {"c": conv},
                    )
                )
                .mappings()
                .one_or_none()
            )
            assert handoff is not None, "a human_handoffs row must be created"
            assert handoff["reason"] == "obstacle_no_solution", (
                f"handoff reason should be the suggested value, got {handoff['reason']!r}"
            )
            paused = (
                await conn.execute(
                    text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
                    {"c": conv},
                )
            ).scalar()
            assert paused is True, "bot must be paused after a suggested handoff"
    finally:
        await engine.dispose()


async def test_no_handoff_when_suggested_handoff_is_none(fresh_tenant):
    """Sanity: a normal composer output (suggested_handoff=None) does
    NOT create a handoff or pause the bot."""
    tid, _cid, conv = fresh_tenant
    from atendia.contracts.message import Message, MessageDirection
    from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.webhooks.meta_routes import build_nlu

    s = get_settings()

    class _NormalComposer:
        async def compose(self, *, input: ComposerInput):
            return (ComposerOutput(messages=["Claro, con gusto te ayudo."]), None)

    engine = create_async_engine(s.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            nlu = build_nlu(s)
            runner = ConversationRunner(session, nlu, _NormalComposer())
            inbound = Message(
                id=str(uuid4()),
                conversation_id=conv,
                tenant_id=tid,
                direction=MessageDirection.INBOUND,
                text="hola, info por favor",
                sent_at=datetime.now(UTC),
                attachments=[],
            )
            await runner.run_turn(
                conversation_id=UUID(conv),
                tenant_id=UUID(tid),
                inbound=inbound,
                turn_number=1,
                arq_pool=None,
                to_phone_e164="+5215999111223",
            )
            await session.commit()

        async with engine.begin() as conn:
            handoff_count = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM human_handoffs WHERE conversation_id = :c"),
                    {"c": conv},
                )
            ).scalar()
            assert handoff_count == 0, "no handoff for a normal turn"
            paused = (
                await conn.execute(
                    text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
                    {"c": conv},
                )
            ).scalar()
            assert paused is False, "bot stays active for a normal turn"
    finally:
        await engine.dispose()

"""Zero-side-effects invariant for run_sandbox_turn (harness task 3).

The harness runs the REAL ConversationRunner against a real seeded
conversation. The whole point of this test is the invariant: after a
sandbox turn, the row counts for every table the runner can write
(messages, turn_traces, field_suggestions, outbound_outbox) are
UNCHANGED, because the runner never commits and the harness always
rolls back. Counts are taken in FRESH sessions so a committed write
elsewhere would be visible — proving nothing leaked.

Note the real outbox table is `outbound_outbox` (not `outbox`); it has
no conversation_id, so it is filtered by the seeded tenant_id (unique
per test). Seeding/cleanup use their own committed sessions, mirroring
tests/runner/conftest.py (no shared db_session fixture in tests/sandbox).
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.sandbox.harness import run_sandbox_turn
from tests.runner.test_conversation_runner import (
    _FakeNLUWithCost,
    _RecordingComposer,
    _seed_tenant_with_pipeline,
)


async def _count_side_effect_rows(
    session: AsyncSession,
    *,
    conversation_id,
    tenant_id,
) -> dict[str, int]:
    """Snapshot row counts for every table the runner can write."""
    counts: dict[str, int] = {}
    for table in ("messages", "turn_traces", "field_suggestions"):
        counts[table] = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE conversation_id = :c"),
                {"c": conversation_id},
            )
        ).scalar()
    # outbound_outbox has no conversation_id column — scope by tenant
    # (the seeded tenant is unique to this test).
    counts["outbound_outbox"] = (
        await session.execute(
            text("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar()
    return counts


@pytest.mark.asyncio
async def test_run_sandbox_turn_persists_nothing():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed a real tenant + customer + conversation + conversation_state
    # row using the runner suite's committed helper.
    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(
            seed_session, "test_sandbox_no_side_effects"
        )

    try:
        # Snapshot counts in a FRESH session (sees committed state only).
        async with factory() as before_session:
            before = await _count_side_effect_rows(
                before_session, conversation_id=conv_id, tenant_id=tid
            )

        result = await run_sandbox_turn(
            conversation_id=conv_id,
            tenant_id=tid,
            inbound_text="quiero una moto",
            nlu_provider=_FakeNLUWithCost(Decimal("0.000050")),
            composer_provider=_RecordingComposer(messages=["hola desde sandbox"]),
        )

        # Re-count in another FRESH session.
        async with factory() as after_session:
            after = await _count_side_effect_rows(
                after_session, conversation_id=conv_id, tenant_id=tid
            )

        # INVARIANT: zero persisted writes across all four tables.
        assert after == before, f"sandbox turn leaked rows: before={before} after={after}"
        assert result.composer_output is not None
        assert isinstance(result.would_be_outbound, list)
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()

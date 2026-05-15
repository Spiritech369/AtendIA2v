"""Cost accumulation + confirmable cap + multi-turn invariant (harness task 4).

`run_sandbox_conversation` replays a script of inbound messages on ONE
session (so conversation_state accumulates across turns — faithful
multi-turn) and rolls back exactly once at the end. It accumulates
per-turn cost and raises `CostCapExceeded` the moment the running total
exceeds the cap (the tripping turn still counts). `estimate_cost` returns
n_turns * mean-recent-turn-cost for a tenant (fallback when no history).

Seeding/cleanup use their own committed sessions, mirroring
tests/runner/conftest.py (no shared db_session fixture in tests/sandbox).
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.sandbox.harness import estimate_cost, run_sandbox_conversation
from atendia.sandbox.result import CostCapExceeded
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
    counts: dict[str, int] = {}
    for table in ("messages", "turn_traces", "field_suggestions"):
        counts[table] = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE conversation_id = :c"),
                {"c": conversation_id},
            )
        ).scalar()
    counts["outbound_outbox"] = (
        await session.execute(
            text("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar()
    return counts


@pytest.mark.asyncio
async def test_cost_cap_raised_after_tripping_turn():
    """3-msg script, each turn costs 0.05, cap=0.08 → raise after turn 2."""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(seed_session, "test_sandbox_cost_cap")

    try:
        composer = _RecordingComposer(messages=["respuesta sandbox"])
        with pytest.raises(CostCapExceeded) as exc_info:
            await run_sandbox_conversation(
                conversation_id=conv_id,
                tenant_id=tid,
                script=["uno", "dos", "tres"],
                cost_cap_usd=Decimal("0.08"),
                nlu_provider=_FakeNLUWithCost(Decimal("0.05")),
                composer_provider=composer,
            )

        exc = exc_info.value
        assert len(exc.partial) == 2, f"tripping turn must still count: {exc.partial!r}"
        assert exc.spent == Decimal("0.10"), f"spent should include turn 2: {exc.spent!r}"
        assert all(t.cost_usd == Decimal("0.05") for t in exc.partial)
        # turn 3 never ran (composer invoked once per turn → exactly 2 times)
        assert composer.call_count == 2
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sandbox_conversation_persists_nothing():
    """Multi-turn invariant: an N-message replay persists zero rows."""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(
            seed_session, "test_sandbox_multiturn_no_side_effects"
        )

    try:
        async with factory() as before_session:
            before = await _count_side_effect_rows(
                before_session, conversation_id=conv_id, tenant_id=tid
            )

        result = await run_sandbox_conversation(
            conversation_id=conv_id,
            tenant_id=tid,
            script=["hola", "quiero una moto", "cuanto cuesta"],
            cost_cap_usd=None,
            nlu_provider=_FakeNLUWithCost(Decimal("0.000050")),
            composer_provider=_RecordingComposer(messages=["hola desde sandbox"]),
        )

        async with factory() as after_session:
            after = await _count_side_effect_rows(
                after_session, conversation_id=conv_id, tenant_id=tid
            )

        assert after == before, f"multi-turn sandbox leaked rows: before={before} after={after}"
        assert len(result.turns) == 3
        assert result.total_cost_usd == Decimal("0.000150")
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_estimate_cost_fallback_when_no_history():
    """No turn_traces for the tenant → constant fallback (0.02/turn)."""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as seed_session:
        tid, _cid, _conv_id = await _seed_tenant_with_pipeline(
            seed_session, "test_sandbox_estimate_fallback"
        )

    try:
        est = await estimate_cost(tenant_id=tid, n_turns=5)
        assert est == Decimal("0.10"), f"expected 5 * 0.02 fallback, got {est!r}"
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_estimate_cost_uses_recent_mean():
    """With history, estimate = n_turns * mean(component-cost-sum) of rows."""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(
            seed_session, "test_sandbox_estimate_history"
        )
        # Two prior turns: sums 0.02 and 0.06 → mean per-turn 0.04.
        await seed_session.execute(
            text(
                "INSERT INTO turn_traces (conversation_id, tenant_id, turn_number, "
                "nlu_cost_usd, composer_cost_usd) VALUES "
                "(:c, :t, 1, 0.010000, 0.010000), "
                "(:c, :t, 2, 0.030000, 0.030000)"
            ),
            {"c": conv_id, "t": tid},
        )
        await seed_session.commit()

    try:
        est = await estimate_cost(tenant_id=tid, n_turns=3)
        assert est == Decimal("0.12"), f"expected 3 * 0.04 mean, got {est!r}"
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()

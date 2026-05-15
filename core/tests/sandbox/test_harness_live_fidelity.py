"""Gated live-LLM fidelity check (harness task 6).

Proves the harness drives the REAL providers end to end — not just the
canned fakes — and STILL persists nothing. respx-mocked tests can't
defend "a real gpt-4o-mini + gpt-4o turn produces a real reply at real
cost with zero DB writes"; this one can.

Gated by RUN_LIVE_LLM_TESTS=1 (costs a cent or two). Run:

    cd core && RUN_LIVE_LLM_TESTS=1 uv run pytest \
        tests/sandbox/test_harness_live_fidelity.py -v
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.nlu_openai import OpenAINLU
from atendia.sandbox.harness import run_sandbox_turn
from tests.runner.test_conversation_runner import _seed_tenant_with_pipeline

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI calls (costs money)",
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
async def test_live_sandbox_turn_real_providers_zero_side_effects():
    api_key = get_settings().openai_api_key
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY for live tests"

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(
            seed_session, "test_sandbox_live_fidelity"
        )

    try:
        async with factory() as before_session:
            before = await _count_side_effect_rows(
                before_session, conversation_id=conv_id, tenant_id=tid
            )

        result = await run_sandbox_turn(
            conversation_id=conv_id,
            tenant_id=tid,
            inbound_text="hola, quiero información de una moto Italika, soy de CDMX",
            nlu_provider=OpenAINLU(api_key=api_key),
            composer_provider=OpenAIComposer(api_key=api_key),
        )

        async with factory() as after_session:
            after = await _count_side_effect_rows(
                after_session, conversation_id=conv_id, tenant_id=tid
            )

        # Real reply produced...
        assert result.composer_output is not None
        assert result.would_be_outbound, f"no would-be reply: {result!r}"
        assert "".join(result.would_be_outbound).strip(), "reply text was empty"
        # ...at real cost...
        assert result.cost_usd > 0, f"real LLM turn should cost > 0: {result.cost_usd!r}"
        # ...with zero persisted rows (the whole point of the harness).
        assert after == before, f"live sandbox turn leaked rows: before={before} after={after}"
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()

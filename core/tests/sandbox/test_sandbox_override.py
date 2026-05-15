"""Rolled-back override hook (harness task 5).

A4/A3 need to run the real runner with a *different* agent prompt
WITHOUT touching production config. Mechanism: a pre-run async callback
that mutates the agent row INSIDE the sandbox session. The runner's
_load_agent then naturally loads the overridden config (same session,
flushed), and the harness's single rollback discards the mutation so
the production row is untouched.

The agent's system_prompt flows into brand_facts["agent_system_prompt"]
(conversation_runner.py ~728), and brand_facts is a ComposerInput field
— so _RecordingComposer.last_input is the faithful capture point.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.db.models.agent import Agent
from atendia.sandbox.harness import run_sandbox_turn
from tests.runner.test_conversation_runner import (
    _FakeNLUWithCost,
    _RecordingComposer,
    _seed_tenant_with_pipeline,
)


@pytest.mark.asyncio
async def test_override_visible_to_runner_then_rolled_back():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(seed_session, "test_sandbox_override")
        agent_id = (
            await seed_session.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, is_default, system_prompt) "
                    "VALUES (gen_random_uuid(), :t, 'SandboxBot', true, 'PROMPT_A') "
                    "RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar()
        await seed_session.commit()

    async def _override(session: AsyncSession) -> None:
        await session.execute(
            update(Agent).where(Agent.id == agent_id).values(system_prompt="PROMPT_B")
        )

    try:
        composer = _RecordingComposer(messages=["respuesta"])
        await run_sandbox_turn(
            conversation_id=conv_id,
            tenant_id=tid,
            inbound_text="hola",
            nlu_provider=_FakeNLUWithCost(Decimal("0.000050")),
            composer_provider=composer,
            apply_overrides=_override,
        )

        # (a) the runner loaded the OVERRIDDEN prompt within the sandbox txn
        assert composer.last_input is not None
        assert composer.last_input.brand_facts.get("agent_system_prompt") == "PROMPT_B", (
            f"runner did not see the override: "
            f"{composer.last_input.brand_facts.get('agent_system_prompt')!r}"
        )

        # (b) production row is UNTOUCHED — the override was rolled back
        async with factory() as check_session:
            persisted = (
                await check_session.execute(
                    text("SELECT system_prompt FROM agents WHERE id = :a"),
                    {"a": agent_id},
                )
            ).scalar()
        assert persisted == "PROMPT_A", f"override leaked into production: {persisted!r}"
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await cleanup_session.commit()
        await engine.dispose()

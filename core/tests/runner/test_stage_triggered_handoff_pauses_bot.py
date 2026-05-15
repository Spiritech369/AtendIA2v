"""Wave1 latent-bug regression — STAGE_TRIGGERED_HANDOFF must pause the
bot via `conversation_state`, not `conversations`.

`_trigger_stage_entry_handoff` (the path that fires when a conversation
enters a stage with `pause_bot_on_enter=true`) flipped the gate with

    UPDATE conversations SET bot_paused = true WHERE id = :cid

but `bot_paused` lives on `conversation_state` (the column the
top-of-`run_turn` SELECT/JOIN actually reads). The sibling
composer-suggested handoff site 100 lines above does it correctly
(`UPDATE conversation_state ... WHERE conversation_id = :cid`).

This test seeds tenant+customer+conversation+conversation_state, drives
`_trigger_stage_entry_handoff` directly with a custom pipeline whose
target stage has `pause_bot_on_enter=true`, then asserts against a
REAL database that:

  * a `human_handoffs` row exists, and
  * `conversation_state.bot_paused` is True.

We invoke the helper directly (rather than a full `run_turn`) so the
routing into the pause stage is deterministic — no dependence on NLU
classifying a crafted inbound into a specific stage. The buggy UPDATE
targets a column that does not exist on `conversations`, so against a
real Postgres it raises `UndefinedColumnError` (the handoff path was
CRASHING, not merely dead-writing the wrong flag).
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
)


@pytest.fixture
def fresh_tenant() -> tuple[str, str, str]:
    """Tenant + customer + conversation + conversation_state, cleaned up after."""

    async def _seed() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"wave1_stage_handoff_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Wave1 Test') RETURNING id"
                        ),
                        {"t": tid, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
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


def _pipeline_with_pause_stage() -> PipelineDefinition:
    """A 2-stage pipeline: `nuevo` (initial) and `escalado` which sets
    `pause_bot_on_enter=true` + a stage-level handoff reason."""
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(id="nuevo", actions_allowed=["greet"]),
            StageDefinition(
                id="escalado",
                label="Escalado a humano",
                actions_allowed=["escalate_to_human"],
                is_terminal=False,
                pause_bot_on_enter=True,
                handoff_reason="obstacle_no_solution",
            ),
        ],
        fallback="ask_clarification",
        docs_per_plan={"nomina_tarjeta_10": ["DOCS_INE"]},
    )


async def test_stage_triggered_handoff_pauses_bot_via_conversation_state(fresh_tenant):
    """Entering a `pause_bot_on_enter=true` stage must:
      * create a `human_handoffs` row, and
      * flip `conversation_state.bot_paused` to True.

    RED before the fix: the buggy `UPDATE conversations SET bot_paused`
    targets a non-existent column → the helper raises (the handoff path
    was crashing). GREEN after retargeting the UPDATE at
    `conversation_state`.
    """
    tid, _cid, conv = fresh_tenant
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.webhooks.meta_routes import build_nlu

    s = get_settings()
    engine = create_async_engine(s.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            nlu = build_nlu(s)
            # Composer is never invoked — the helper short-circuits the
            # turn — but the ctor requires a provider.
            runner = ConversationRunner(session, nlu, _StubComposer())
            triggered = await runner._trigger_stage_entry_handoff(
                tenant_id=UUID(tid),
                conversation_id=UUID(conv),
                pipeline=_pipeline_with_pause_stage(),
                new_stage_id="escalado",
                last_inbound_text="esto no me sirve, ya intenté de todo",
                merged_extracted={},
            )
            await session.commit()

        assert triggered is True, (
            "the stage has pause_bot_on_enter=true so the helper must "
            "report it triggered the handoff"
        )

        async with engine.begin() as conn:
            paused = (
                await conn.execute(
                    text("SELECT bot_paused FROM conversation_state WHERE conversation_id = :c"),
                    {"c": conv},
                )
            ).scalar()
            assert paused is True, (
                "stage-triggered handoff must pause the bot via conversation_state"
            )

            handoff = (
                (
                    await conn.execute(
                        text(
                            "SELECT reason FROM human_handoffs "
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
                f"handoff reason should be the stage override, got {handoff['reason']!r}"
            )
    finally:
        await engine.dispose()


class _StubComposer:
    # `input` mirrors ComposerProtocol's keyword name (shadows a builtin
    # by design — the protocol dictates the parameter name).
    async def compose(self, *, input):
        raise AssertionError("composer must not be invoked on a stage-triggered handoff")

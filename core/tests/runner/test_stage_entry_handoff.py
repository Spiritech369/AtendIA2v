"""Unit tests for the Fase 4 stage-entry handoff helper.

The runner's `_trigger_stage_entry_handoff` couples six concerns:

  1. detect the stage's `pause_bot_on_enter` flag,
  2. resolve the `handoff_reason` (stage override > generic),
  3. build + persist a HandoffSummary,
  4. flip `conversation_state.bot_paused = true`,
  5. emit DOCS_COMPLETE_FOR_PLAN (when the stage uses that operator)
     + BOT_PAUSED + HUMAN_HANDOFF_REQUESTED system events,
  6. tell the caller to skip composer via the returned bool.

We exercise it against a hand-built `_FakeSession` that records SQL +
ORM `.add()` calls — no DB. The composer-skip side of the contract
(the `auto_handoff_triggered` branch in `run_turn`) is verified at the
integration layer in Fase 7; here we focus on the helper itself.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.contracts.event import EventType
from atendia.contracts.pipeline_definition import (
    AutoEnterRules,
    Condition,
    PipelineDefinition,
    StageDefinition,
)
from atendia.db.models import MessageRow
from atendia.runner.conversation_runner import ConversationRunner

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeSession:
    """Captures session.add() rows + session.execute() SQL fragments.

    Keeps the assertion surface focused on what the helper writes, not
    on SQLAlchemy plumbing.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.executed_sql: list[str] = []
        # human_handoffs INSERT goes through .execute(text(...), {...});
        # we capture the param dict so the test can assert reason + payload.
        self.executed_params: list[dict] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt: Any, params: dict | None = None) -> Any:
        # Best-effort SQL stringify; works for sqlalchemy.text() compiled
        # forms and plain str alike.
        sql = str(stmt) if not hasattr(stmt, "text") else stmt.text
        self.executed_sql.append(sql)
        self.executed_params.append(params or {})
        return MagicMock()

    def messages(self) -> list[MessageRow]:
        return [o for o in self.added if isinstance(o, MessageRow)]

    def system_messages_by_event(self) -> dict[str, MessageRow]:
        out: dict[str, MessageRow] = {}
        for m in self.messages():
            evt = (m.metadata_json or {}).get("event_type")
            if isinstance(evt, str):
                out.setdefault(evt, m)
        return out


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    session = _FakeSession()
    # Stub EventEmitter so events table inserts don't try to touch DB.
    fake_emitter = MagicMock()
    fake_emitter.emit = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "atendia.runner.conversation_events.EventEmitter",
        lambda _s: fake_emitter,
    )
    # The ConversationRunner constructor builds its own _emitter — patch
    # the class so the runner uses the same stub.
    monkeypatch.setattr(
        "atendia.runner.conversation_runner.EventEmitter",
        lambda _s: fake_emitter,
    )
    session._fake_emitter = fake_emitter  # type: ignore[attr-defined]
    return session


def _runner_for(session: _FakeSession) -> ConversationRunner:
    """ConversationRunner with stub NLU + Composer providers — we don't
    invoke run_turn, just the helper method."""
    return ConversationRunner(
        session=session,  # type: ignore[arg-type]
        nlu_provider=MagicMock(),
        composer_provider=MagicMock(),
    )


def _papeleria_completa_stage(
    *,
    pause_on_enter: bool = True,
    reason: str | None = "docs_complete_for_plan",
    uses_docs_complete: bool = True,
) -> StageDefinition:
    rules: AutoEnterRules | None = None
    if uses_docs_complete:
        rules = AutoEnterRules(
            enabled=True,
            match="all",
            conditions=[
                Condition(
                    field="plan_credito",
                    operator="docs_complete_for_plan",
                ),
            ],
        )
    return StageDefinition(
        id="papeleria_completa",
        label="Papelería completa",
        actions_allowed=["escalate_to_human"],
        is_terminal=False,
        pause_bot_on_enter=pause_on_enter,
        handoff_reason=reason,
        auto_enter_rules=rules,
    )


def _pipeline_with(stage: StageDefinition) -> PipelineDefinition:
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(id="nuevo", actions_allowed=["greet"]),
            stage,
        ],
        fallback="ask_clarification",
        docs_per_plan={"nomina_tarjeta_10": ["DOCS_INE"]},
    )


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_does_nothing_when_pause_bot_on_enter_false(fake_session):
    runner = _runner_for(fake_session)
    stage = _papeleria_completa_stage(pause_on_enter=False)
    triggered = await runner._trigger_stage_entry_handoff(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        pipeline=_pipeline_with(stage),
        new_stage_id="papeleria_completa",
        last_inbound_text="📎",
        merged_extracted={"plan_credito": {"value": "nomina_tarjeta_10"}},
    )
    assert triggered is False
    assert fake_session.messages() == []
    assert fake_session.executed_sql == []


@pytest.mark.asyncio
async def test_returns_false_when_stage_id_not_in_pipeline(fake_session):
    runner = _runner_for(fake_session)
    stage = _papeleria_completa_stage()
    triggered = await runner._trigger_stage_entry_handoff(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        pipeline=_pipeline_with(stage),
        new_stage_id="some_other_stage",
        last_inbound_text="📎",
        merged_extracted={},
    )
    assert triggered is False


@pytest.mark.asyncio
async def test_full_handoff_flow_persists_pauses_emits(fake_session):
    """Happy path: stage has pause_bot_on_enter=true + uses
    docs_complete_for_plan operator. Expect:
      - human_handoffs INSERT
      - UPDATE conversation_state SET bot_paused=true
      - system messages for DOCS_COMPLETE_FOR_PLAN, BOT_PAUSED, HUMAN_HANDOFF_REQUESTED
      - EventEmitter.emit() called for HUMAN_HANDOFF_REQUESTED
      - returns True
    """
    runner = _runner_for(fake_session)
    stage = _papeleria_completa_stage()
    tenant_id = uuid4()
    conversation_id = uuid4()
    triggered = await runner._trigger_stage_entry_handoff(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        pipeline=_pipeline_with(stage),
        new_stage_id="papeleria_completa",
        last_inbound_text="ya está todo",
        merged_extracted={
            "plan_credito": {"value": "10%"},
            "nombre": {"value": "Juan"},
        },
    )
    assert triggered is True

    # 1. human_handoffs INSERT happened with the reason.
    insert_calls = [
        params
        for sql, params in zip(
            fake_session.executed_sql,
            fake_session.executed_params,
        )
        if "INSERT INTO human_handoffs" in sql
    ]
    assert len(insert_calls) == 1
    assert insert_calls[0]["r"] == "docs_complete_for_plan"

    # 2. conversation_state.bot_paused flipped to true.
    pause_calls = [
        params
        for sql, params in zip(
            fake_session.executed_sql,
            fake_session.executed_params,
        )
        if "bot_paused = true" in sql
    ]
    assert len(pause_calls) == 1
    assert pause_calls[0]["cid"] == conversation_id

    # 3. Three distinct system event bubbles: DOCS_COMPLETE_FOR_PLAN,
    #    BOT_PAUSED, HUMAN_HANDOFF_REQUESTED.
    by_event = fake_session.system_messages_by_event()
    assert "docs_complete_for_plan" in by_event
    assert "bot_paused" in by_event
    assert "human_handoff_requested" in by_event

    # 4. HUMAN_HANDOFF_REQUESTED also went through the events table emit
    #    (workflows engine listens here).
    awaited = fake_session._fake_emitter.emit.await_args_list
    handoff_calls = [
        c for c in awaited if c.kwargs.get("event_type") == EventType.HUMAN_HANDOFF_REQUESTED
    ]
    assert len(handoff_calls) >= 1
    payload = handoff_calls[0].kwargs.get("payload") or {}
    assert payload.get("reason") == "docs_complete_for_plan"
    assert payload.get("stage") == "papeleria_completa"


@pytest.mark.asyncio
async def test_skips_docs_complete_bubble_when_rule_uses_different_operator(fake_session):
    """A stage that pauses-on-enter but doesn't use the
    docs_complete_for_plan operator should NOT pretend papelería is
    complete — the bubble would mislead the operator."""
    runner = _runner_for(fake_session)
    stage = _papeleria_completa_stage(
        reason="user_signaled_papeleria_completa",
        uses_docs_complete=False,  # no docs_complete_for_plan condition
    )
    triggered = await runner._trigger_stage_entry_handoff(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        pipeline=_pipeline_with(stage),
        new_stage_id="papeleria_completa",
        last_inbound_text="ya tengo todo",
        merged_extracted={"plan_credito": {"value": "10%"}},
    )
    assert triggered is True
    by_event = fake_session.system_messages_by_event()
    assert "docs_complete_for_plan" not in by_event
    assert "bot_paused" in by_event
    assert "human_handoff_requested" in by_event


@pytest.mark.asyncio
async def test_unknown_handoff_reason_falls_back_to_generic(fake_session):
    """Operator-authored stages can write `handoff_reason="anything"`;
    the helper should not crash. Reason not in the enum → generic
    STAGE_TRIGGERED_HANDOFF persisted instead."""
    runner = _runner_for(fake_session)
    stage = _papeleria_completa_stage(reason="some_custom_label_v37")
    triggered = await runner._trigger_stage_entry_handoff(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        pipeline=_pipeline_with(stage),
        new_stage_id="papeleria_completa",
        last_inbound_text="hi",
        merged_extracted={},
    )
    assert triggered is True
    insert_params = next(
        params
        for sql, params in zip(
            fake_session.executed_sql,
            fake_session.executed_params,
        )
        if "INSERT INTO human_handoffs" in sql
    )
    assert insert_params["r"] == "stage_triggered_handoff"


def test_stage_uses_docs_complete_for_plan_helper_pure():
    """Static helper: just inspects auto_enter_rules. No DB, no session."""
    stage_with = _papeleria_completa_stage(uses_docs_complete=True)
    stage_without = _papeleria_completa_stage(uses_docs_complete=False)
    assert ConversationRunner._stage_uses_docs_complete_for_plan(stage_with) is True
    assert ConversationRunner._stage_uses_docs_complete_for_plan(stage_without) is False


# ---------------------------------------------------------------------------
# Real-DB regression guard
#
# The behavior tests above run against _FakeSession, which records the SQL
# text but never executes it. That string-match masked a bug: the helper
# wrote `UPDATE conversations SET bot_paused = true`, but bot_paused only
# exists on conversation_state — the column the top-of-run_turn pause gate
# actually reads. Against a real Postgres this raises UndefinedColumnError.
# This test seeds real rows, runs the helper against a real AsyncSession,
# and asserts the pause is observable where the gate looks for it, so the
# bug cannot regress behind a mocked session again.
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_conversation() -> tuple[str, str]:
    """Real tenant + customer + conversation + conversation_state row.

    Mirrors the seed/cleanup fixture in test_runner_suggested_handoff.py.
    The conversation_state row MUST exist: the fix targets it with an
    UPDATE, and an UPDATE against a missing row is a silent no-op that
    would let this regression guard pass for the wrong reason.
    """

    async def _seed() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"stage_handoff_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Stage Handoff Test') RETURNING id"
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
            return str(tid), str(conv)
        finally:
            await engine.dispose()

    async def _cleanup(tid: str) -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await engine.dispose()

    tid, conv = asyncio.run(_seed())
    yield tid, conv
    asyncio.run(_cleanup(tid))


@pytest.mark.asyncio
async def test_stage_entry_handoff_pauses_bot_in_conversation_state_real_db(
    seeded_conversation,
):
    """Entering a `pause_bot_on_enter` stage must flip
    conversation_state.bot_paused to True — the column the
    top-of-run_turn short-circuit reads. Verified against a real row,
    not a mocked-SQL string match."""
    tid, conv = seeded_conversation
    s = get_settings()
    engine = create_async_engine(s.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            runner = ConversationRunner(
                session=session,  # type: ignore[arg-type]
                nlu_provider=MagicMock(),
                composer_provider=MagicMock(),
            )
            stage = _papeleria_completa_stage()
            triggered = await runner._trigger_stage_entry_handoff(
                tenant_id=UUID(tid),
                conversation_id=UUID(conv),
                pipeline=_pipeline_with(stage),
                new_stage_id="papeleria_completa",
                last_inbound_text="ya tengo toda la papelería",
                merged_extracted={"plan_credito": {"value": "nomina_tarjeta_10"}},
            )
            await session.commit()

        assert triggered is True

        async with engine.begin() as conn:
            paused = (
                await conn.execute(
                    text(
                        "SELECT bot_paused FROM conversation_state "
                        "WHERE conversation_id = :c"
                    ),
                    {"c": conv},
                )
            ).scalar()
            assert paused is True, (
                "bot_paused must be True on conversation_state after a "
                "pause_bot_on_enter stage is entered"
            )
    finally:
        await engine.dispose()

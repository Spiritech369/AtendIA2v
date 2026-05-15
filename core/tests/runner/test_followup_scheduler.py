"""Unit tests for the Phase 3d follow-up scheduler primitives."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.runner.followup_scheduler import (
    FOLLOWUP_KINDS,
    cancel_pending_followups,
    render_followup_body,
    schedule_followups_after_outbound,
)


async def _seed_tenant_conv(db_session) -> tuple:
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
            {"n": f"test_3d_{uuid4().hex[:8]}"},
        )
    ).scalar()
    cust = (
        await db_session.execute(
            text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
            {"t": tid, "p": f"+52155555{uuid4().int % 100000:05d}"},
        )
    ).scalar()
    conv = (
        await db_session.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": tid, "c": cust},
        )
    ).scalar()
    await db_session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conv},
    )
    await db_session.commit()
    return tid, conv


async def _cleanup(db_session, tid):
    await db_session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
    await db_session.commit()


# ============================================================================
# render_followup_body
# ============================================================================


def test_render_3h_silence_is_static_copy() -> None:
    body = render_followup_body(kind="3h_silence", extracted_data={})
    assert "camión" in body
    assert "moto" in body


def test_render_12h_silence_uses_modelo_when_present() -> None:
    body = render_followup_body(
        kind="12h_silence",
        extracted_data={"modelo_moto": {"value": "Adventure 150 CC"}},
    )
    assert "Adventure 150 CC" in body
    assert "sigues en pie" in body


def test_render_12h_silence_falls_back_to_generic_moto() -> None:
    """Silent at 12h with no model captured yet — graceful degrade."""
    body = render_followup_body(kind="12h_silence", extracted_data={})
    assert "moto" in body
    assert "{modelo" not in body  # no leaked placeholder


def test_render_12h_silence_includes_plan_when_known() -> None:
    body = render_followup_body(
        kind="12h_silence",
        extracted_data={
            "modelo_moto": {"value": "Adventure"},
            "plan_credito": {"value": "10%"},
        },
    )
    assert "10%" in body


def test_render_unknown_kind_degrades_gracefully() -> None:
    """A misconfigured cron kind shouldn't crash the worker."""
    body = render_followup_body(kind="bogus_kind", extracted_data={})
    assert "trámite" in body
    assert "{" not in body  # no leaked placeholders


def test_render_accepts_flat_extracted_data_shape() -> None:
    """Both {field: {value: x}} and {field: x} work; tests both."""
    body = render_followup_body(
        kind="12h_silence",
        extracted_data={"modelo_moto": "150Z"},
    )
    assert "150Z" in body


# ============================================================================
# schedule_followups_after_outbound
# ============================================================================


@pytest.mark.asyncio
async def test_schedule_creates_two_pending_rows(db_session) -> None:
    tid, conv = await _seed_tenant_conv(db_session)
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot={"plan_credito": {"value": "10%"}},
    )
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT kind, status, cancelled_at FROM followups_scheduled "
                "WHERE conversation_id = :c ORDER BY kind"
            ),
            {"c": conv},
        )
    ).fetchall()
    kinds = [r[0] for r in rows]
    assert set(kinds) == set(FOLLOWUP_KINDS)
    for r in rows:
        assert r[1] == "pending"
        assert r[2] is None
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_schedule_is_idempotent(db_session) -> None:
    """Calling schedule twice doesn't create duplicate pending rows."""
    tid, conv = await _seed_tenant_conv(db_session)
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot={},
    )
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot={},
    )
    await db_session.commit()

    count = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM followups_scheduled "
                "WHERE conversation_id = :c AND status = 'pending'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert count == 2  # Still just the 3h + 12h pair, not 4.
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_schedule_respects_cancelled_rows(db_session) -> None:
    """A cancelled row from a previous turn does NOT block re-scheduling."""
    tid, conv = await _seed_tenant_conv(db_session)
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot={},
    )
    cancelled = await cancel_pending_followups(
        session=db_session,
        conversation_id=conv,
    )
    assert cancelled == 2

    # Now schedule again — should arm two new rows since the previous ones
    # are cancelled (not pending).
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot={},
    )
    await db_session.commit()
    pending = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM followups_scheduled "
                "WHERE conversation_id = :c AND status = 'pending'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert pending == 2
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_schedule_persists_extracted_snapshot_as_jsonb(db_session) -> None:
    """The audit `context` column carries the snapshot JSON-encoded."""
    tid, conv = await _seed_tenant_conv(db_session)
    snapshot = {"modelo_moto": {"value": "Adventure"}, "plan_credito": {"value": "10%"}}
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot=snapshot,
    )
    await db_session.commit()
    ctx_rows = (
        await db_session.execute(
            text("SELECT context FROM followups_scheduled WHERE conversation_id = :c"),
            {"c": conv},
        )
    ).fetchall()
    for row in ctx_rows:
        # JSONB round-trips as Python dict.
        assert isinstance(row[0], dict)
        assert row[0]["modelo_moto"]["value"] == "Adventure"
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_schedule_run_at_is_in_the_future(db_session) -> None:
    """Sanity: 3h is ~3h ahead, 12h is ~12h ahead. Tolerance for clock skew."""
    tid, conv = await _seed_tenant_conv(db_session)
    before = datetime.now(UTC)
    await schedule_followups_after_outbound(
        session=db_session,
        conversation_id=conv,
        tenant_id=tid,
        extracted_snapshot={},
    )
    await db_session.commit()
    rows = (
        await db_session.execute(
            text("SELECT kind, run_at FROM followups_scheduled WHERE conversation_id = :c"),
            {"c": conv},
        )
    ).fetchall()
    by_kind = {r[0]: r[1] for r in rows}
    delta_3h = by_kind["3h_silence"] - before
    delta_12h = by_kind["12h_silence"] - before
    assert timedelta(hours=2, minutes=59) < delta_3h < timedelta(hours=3, minutes=1)
    assert timedelta(hours=11, minutes=59) < delta_12h < timedelta(hours=12, minutes=1)
    await _cleanup(db_session, tid)


# ============================================================================
# cancel_pending_followups
# ============================================================================


@pytest.mark.asyncio
async def test_cancel_marks_pending_only(db_session) -> None:
    tid, conv = await _seed_tenant_conv(db_session)
    # Insert one pending + one already-sent + one already-cancelled row.
    await db_session.execute(
        text(
            "INSERT INTO followups_scheduled "
            "(conversation_id, tenant_id, run_at, status, kind) "
            "VALUES (:c, :t, NOW() + interval '1 hour', 'pending', '3h_silence'), "
            "       (:c, :t, NOW() - interval '1 hour', 'sent', '12h_silence'), "
            "       (:c, :t, NOW() - interval '2 hours', 'cancelled', '3h_silence')"
        ),
        {"c": conv, "t": tid},
    )
    await db_session.commit()

    n = await cancel_pending_followups(session=db_session, conversation_id=conv)
    await db_session.commit()
    assert n == 1  # Only the pending row gets flipped.

    statuses = (
        await db_session.execute(
            text(
                "SELECT status, cancelled_at FROM followups_scheduled "
                "WHERE conversation_id = :c ORDER BY status"
            ),
            {"c": conv},
        )
    ).fetchall()
    # cancelled (twice now: original + new), sent (untouched).
    cancelled_count = sum(1 for s in statuses if s[0] == "cancelled")
    sent_count = sum(1 for s in statuses if s[0] == "sent")
    assert cancelled_count == 2
    assert sent_count == 1
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_cancel_no_op_on_clean_conversation(db_session) -> None:
    """Cancelling on a conversation with no follow-ups returns 0, no error."""
    tid, conv = await _seed_tenant_conv(db_session)
    n = await cancel_pending_followups(session=db_session, conversation_id=conv)
    assert n == 0
    await _cleanup(db_session, tid)


# ============================================================================
# Cancellation hooks into runner: an inbound nukes pending followups.
# This is an integration-style test against the real runner.
# ============================================================================


@pytest.mark.asyncio
async def test_inbound_via_runner_cancels_pending_followups(db_session) -> None:
    """Smoke: insert pending follow-ups, run a turn, verify they cancel.

    Relies on the runner's first action being cancel_pending_followups.
    """
    from datetime import datetime
    from decimal import Decimal

    from atendia.contracts.message import Message, MessageDirection
    from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
    from atendia.runner.composer_canned import CannedComposer
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.runner.nlu_protocol import UsageMetadata

    class _StubNLU:
        async def classify(self, **kw):
            return (
                NLUResult(intent=Intent.GREETING, sentiment=Sentiment.NEUTRAL, confidence=0.9),
                UsageMetadata(
                    model="x", tokens_in=0, tokens_out=0, cost_usd=Decimal("0"), latency_ms=1
                ),
            )

    tid, conv = await _seed_tenant_conv(db_session)
    # Need a pipeline for run_turn — minimal one.
    await db_session.execute(
        text(
            "INSERT INTO tenant_pipelines (tenant_id, version, definition, active) "
            "VALUES (:t, 1, :d\\:\\:jsonb, true)"
        ),
        {
            "t": tid,
            "d": json.dumps(
                {
                    "version": 1,
                    "stages": [
                        {"id": "qualify", "actions_allowed": ["greet", "ask_clarification"]}
                    ],
                    "fallback": "ask_clarification",
                }
            ),
        },
    )
    await db_session.execute(
        text("UPDATE conversations SET current_stage = 'qualify' WHERE id = :c"),
        {"c": conv},
    )
    # Seed two pending follow-ups directly.
    await db_session.execute(
        text(
            "INSERT INTO followups_scheduled "
            "(conversation_id, tenant_id, run_at, status, kind) "
            "VALUES (:c, :t, NOW() + interval '3 hours', 'pending', '3h_silence'), "
            "       (:c, :t, NOW() + interval '12 hours', 'pending', '12h_silence')"
        ),
        {"c": conv, "t": tid},
    )
    await db_session.commit()

    runner = ConversationRunner(db_session, _StubNLU(), CannedComposer())
    inbound = Message(
        id=str(uuid4()),
        conversation_id=str(conv),
        tenant_id=str(tid),
        direction=MessageDirection.INBOUND,
        text="hola",
        sent_at=datetime.now(UTC),
    )
    await runner.run_turn(
        conversation_id=conv,
        tenant_id=tid,
        inbound=inbound,
        turn_number=1,
    )
    await db_session.commit()

    pending = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM followups_scheduled "
                "WHERE conversation_id = :c AND status = 'pending'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert pending == 0
    await _cleanup(db_session, tid)

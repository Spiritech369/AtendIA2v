"""Tests for the Phase 3d cron worker `poll_followups`.

The worker fires due `followups_scheduled` rows: renders the body using
LIVE extracted_data, enqueues outbound via the same pipeline as a normal
turn, and updates the row status. Hardened against three failure modes:
  * worker dies between enqueue and status update (idempotent via enqueued_at)
  * customer replies between cron pick and enqueue (race vs cancellation)
  * Meta down / arq down (failed status, attempts incremented)
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

from atendia.queue.followup_worker import _quiet_hours_active, poll_followups


async def _seed_tenant_conv(db_session, *, followups_enabled: bool = True) -> tuple:
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name, followups_enabled) VALUES (:n, :e) RETURNING id"),
            {"n": f"test_3d_w_{uuid4().hex[:8]}", "e": followups_enabled},
        )
    ).scalar()
    cust = (
        await db_session.execute(
            text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
            {"t": tid, "p": f"+5215555{uuid4().int % 1000000:06d}"},
        )
    ).scalar()
    conv = (
        await db_session.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": tid, "c": cust},
        )
    ).scalar()
    await db_session.execute(
        text(
            "INSERT INTO conversation_state (conversation_id, extracted_data) "
            "VALUES (:c, :ed\\:\\:jsonb)"
        ),
        {"c": conv, "ed": json.dumps({"modelo_moto": {"value": "Adventure"}})},
    )
    await db_session.commit()
    return tid, conv


async def _insert_due_followup(
    db_session,
    *,
    conv,
    tid,
    kind: str = "3h_silence",
    minutes_overdue: int = 1,
    status: str = "pending",
    cancelled: bool = False,
    enqueued: bool = False,
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO followups_scheduled "
            "(conversation_id, tenant_id, run_at, status, kind, "
            " cancelled_at, enqueued_at) "
            "VALUES (:c, :t, :ra, :s, CAST(:k AS VARCHAR), "
            "        :ca, :ea)"
        ),
        {
            "c": conv,
            "t": tid,
            "ra": datetime.now(UTC) - timedelta(minutes=minutes_overdue),
            "s": status,
            "k": kind,
            "ca": datetime.now(UTC) if cancelled else None,
            "ea": datetime.now(UTC) if enqueued else None,
        },
    )
    await db_session.commit()


async def _cleanup(db_session, tid):
    await db_session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
    await db_session.commit()


# ============================================================================
# Quiet hours
# ============================================================================


def test_quiet_hours_includes_4_to_13_utc() -> None:
    """22:00-07:00 MX = 04-13 UTC. Suppress sends in this window."""
    for h in (4, 8, 13):
        assert _quiet_hours_active(datetime(2026, 5, 7, h, 0, tzinfo=UTC))
    for h in (3, 14, 0, 23):
        assert not _quiet_hours_active(datetime(2026, 5, 7, h, 0, tzinfo=UTC))


# ============================================================================
# poll_followups: monkeypatch quiet hours so we can test under any clock
# ============================================================================


@pytest.fixture
def fake_arq_redis():
    """Mock arq Redis with the methods enqueue_outbound calls."""
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock(return_value=None)
    return redis


@pytest.mark.asyncio
async def test_poll_skips_when_no_due_rows(db_session, monkeypatch, fake_arq_redis):
    """No rows in pending status → worker returns early with sent=0."""
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    result = await poll_followups({"redis": fake_arq_redis})
    assert result["status"] == "ok"
    assert result["sent"] == 0


@pytest.mark.asyncio
async def test_poll_skips_during_quiet_hours(db_session, monkeypatch, fake_arq_redis):
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: True,
    )
    result = await poll_followups({"redis": fake_arq_redis})
    assert result["status"] == "skipped_quiet_hours"


@pytest.mark.asyncio
async def test_poll_fires_due_3h_and_marks_sent(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    tid, conv = await _seed_tenant_conv(db_session)
    await _insert_due_followup(db_session, conv=conv, tid=tid)

    result = await poll_followups({"redis": fake_arq_redis})

    assert result["sent"] == 1
    fake_arq_redis.enqueue_job.assert_called_once()

    # Row marked sent.
    status = (
        await db_session.execute(
            text(
                "SELECT status FROM followups_scheduled "
                "WHERE conversation_id = :c AND kind = '3h_silence'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert status == "sent"
    # followups_sent_count incremented.
    cnt = (
        await db_session.execute(
            text("SELECT followups_sent_count FROM conversation_state WHERE conversation_id = :c"),
            {"c": conv},
        )
    ).scalar()
    assert cnt == 1
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_poll_skips_cancelled_rows(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    """A row cancelled between scheduling and the cron tick is NOT fired."""
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    tid, conv = await _seed_tenant_conv(db_session)
    await _insert_due_followup(db_session, conv=conv, tid=tid, cancelled=True)
    result = await poll_followups({"redis": fake_arq_redis})
    assert result["sent"] == 0
    fake_arq_redis.enqueue_job.assert_not_called()
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_poll_skips_already_in_flight(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    """A row with enqueued_at != NULL is treated as in-flight, not re-fired."""
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    tid, conv = await _seed_tenant_conv(db_session)
    await _insert_due_followup(db_session, conv=conv, tid=tid, enqueued=True)
    result = await poll_followups({"redis": fake_arq_redis})
    assert result["sent"] == 0
    fake_arq_redis.enqueue_job.assert_not_called()
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_poll_respects_tenant_disable_flag(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    """tenants.followups_enabled = false → cron query filters it out."""
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    tid, conv = await _seed_tenant_conv(db_session, followups_enabled=False)
    await _insert_due_followup(db_session, conv=conv, tid=tid)
    result = await poll_followups({"redis": fake_arq_redis})
    assert result["sent"] == 0
    fake_arq_redis.enqueue_job.assert_not_called()
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_poll_3h_fire_reschedules_pending_12h(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    """When 3h fires, the pending 12h is cancelled and a fresh 12h re-armed."""
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    tid, conv = await _seed_tenant_conv(db_session)
    # 3h is overdue (will fire); 12h is pending future.
    await _insert_due_followup(db_session, conv=conv, tid=tid, kind="3h_silence")
    await db_session.execute(
        text(
            "INSERT INTO followups_scheduled "
            "(conversation_id, tenant_id, run_at, status, kind) "
            "VALUES (:c, :t, NOW() + interval '9 hours', 'pending', '12h_silence')"
        ),
        {"c": conv, "t": tid},
    )
    await db_session.commit()

    await poll_followups({"redis": fake_arq_redis})

    # The original 12h is cancelled.
    cancelled_old = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM followups_scheduled "
                "WHERE conversation_id = :c AND kind = '12h_silence' "
                "  AND status = 'cancelled'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert cancelled_old == 1
    # A new 12h is pending, run_at ~12h from now (we just fired, so this
    # is approximately now+12h).
    new_pending = (
        await db_session.execute(
            text(
                "SELECT COUNT(*), MIN(run_at) FROM followups_scheduled "
                "WHERE conversation_id = :c AND kind = '12h_silence' "
                "  AND status = 'pending'"
            ),
            {"c": conv},
        )
    ).fetchone()
    assert new_pending[0] == 1
    delta = new_pending[1] - datetime.now(UTC)
    assert timedelta(hours=11, minutes=55) < delta < timedelta(hours=12, minutes=5)
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_poll_marks_failed_on_missing_phone(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    """Customer phone lookup returns None → status=failed, no enqueue.

    We monkeypatch the phone-lookup helper instead of deleting the
    customer row directly — FK cascade behavior between conversations,
    customers, and followups_scheduled is environment-dependent and the
    point here is the worker's defense, not the DB schema.
    """
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )

    async def _fake_no_phone(_session, _conversation_id):
        return None

    monkeypatch.setattr(
        "atendia.queue.followup_worker._load_recipient_phone",
        _fake_no_phone,
    )

    tid, conv = await _seed_tenant_conv(db_session)
    await _insert_due_followup(db_session, conv=conv, tid=tid)

    result = await poll_followups({"redis": fake_arq_redis})
    assert result["skipped_no_phone"] == 1
    fake_arq_redis.enqueue_job.assert_not_called()

    status = (
        await db_session.execute(
            text("SELECT status, last_error FROM followups_scheduled WHERE conversation_id = :c"),
            {"c": conv},
        )
    ).fetchone()
    assert status[0] == "failed"
    assert "recipient_phone_missing" in status[1]
    await _cleanup(db_session, tid)


@pytest.mark.asyncio
async def test_poll_caps_at_50_per_tick(
    db_session,
    monkeypatch,
    fake_arq_redis,
):
    """Rate cap: 60 due rows in one tick → only 50 fire, 10 wait."""
    monkeypatch.setattr(
        "atendia.queue.followup_worker._quiet_hours_active",
        lambda _now: False,
    )
    tid, conv = await _seed_tenant_conv(db_session)
    # Seed 60 due rows.
    for _ in range(60):
        await db_session.execute(
            text(
                "INSERT INTO followups_scheduled "
                "(conversation_id, tenant_id, run_at, status, kind) "
                "VALUES (:c, :t, NOW() - interval '1 minute', 'pending', '3h_silence')"
            ),
            {"c": conv, "t": tid},
        )
    await db_session.commit()

    result = await poll_followups({"redis": fake_arq_redis})
    assert result["sent"] == 50  # _RATE_CAP_PER_TICK

    # The trailing 10 unfired 3h_silence rows wait for the next tick.
    unfired_3h = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM followups_scheduled "
                "WHERE conversation_id = :c AND kind = '3h_silence' "
                "  AND status = 'pending'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert unfired_3h == 10
    # Plus exactly ONE pending 12h_silence — each 3h fire's reschedule
    # cancels the previous 12h and inserts a fresh one, so on the same
    # conversation only the most-recent 12h survives.
    pending_12h = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM followups_scheduled "
                "WHERE conversation_id = :c AND kind = '12h_silence' "
                "  AND status = 'pending'"
            ),
            {"c": conv},
        )
    ).scalar()
    assert pending_12h == 1
    await _cleanup(db_session, tid)

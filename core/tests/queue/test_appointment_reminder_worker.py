"""Sprint B.4 — Auto-dispatch appointment reminders 24h before scheduled_at.

Pre-Sprint state: appointments persisted but no reminders fired unless an
operator wired a workflow trigger by hand. Audit said:
  "🟢 Sin reminder scheduler real | La cita persiste pero no auto-envía
   recordatorios — sólo si workflow está configurado."

This worker closes that gap by polling once per minute, picking
appointments due for their 24h reminder, marking them as sent, and
emitting `admin.appointment.reminder_due_24h` events. Actual WhatsApp
delivery still depends on the messaging provider (Demo/Empty today;
a real Meta-backed provider can subscribe to the event).

These tests pin the scheduling contract:
* An appointment scheduled ~24h ahead with `reminder_status='pending'`
  moves to `sent_24h` after one poll tick.
* An appointment outside the window stays untouched.
* A cancelled or completed appointment is never reminded.
* A second tick within the same minute is idempotent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings
from atendia.queue.appointment_reminder_worker import poll_appointment_reminders


@pytest.fixture
def tenant_with_customer() -> tuple[str, str]:
    """Insert a throwaway tenant + customer; teardown after."""

    async def _seed() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"reminder_test_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Reminder Test') RETURNING id"
                        ),
                        {"t": tid, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
            return str(tid), str(cid)
        finally:
            await engine.dispose()

    async def _cleanup(tid: str) -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await engine.dispose()

    tid, cid = asyncio.run(_seed())
    yield tid, cid
    asyncio.run(_cleanup(tid))


async def _insert_appointment(
    tenant_id: str,
    customer_id: str,
    *,
    scheduled_at: datetime,
    status: str = "scheduled",
    reminder_status: str = "pending",
) -> str:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            # `created_by_type` set explicitly to dodge a pre-existing
            # schema bug: migration 026 emitted DEFAULT '''user'''
            # (3 single quotes) for this column, so any INSERT without
            # an explicit value lands a literal "'user'" — which then
            # fails ck_appointments_created_by_type. The runtime code
            # always sets it via the SQLAlchemy model's Python-level
            # default; raw-SQL tests need to mirror that.
            aid = (
                await conn.execute(
                    text(
                        "INSERT INTO appointments "
                        "(tenant_id, customer_id, scheduled_at, service, status, "
                        " reminder_status, created_by_type) "
                        "VALUES (:t, :c, :sa, 'test-drive', :st, :rs, 'user') "
                        "RETURNING id"
                    ),
                    {
                        "t": tenant_id,
                        "c": customer_id,
                        "sa": scheduled_at,
                        "st": status,
                        "rs": reminder_status,
                    },
                )
            ).scalar()
        return str(aid)
    finally:
        await engine.dispose()


async def _appointment_reminder_status(appointment_id: str) -> str:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT reminder_status FROM appointments WHERE id = :i"),
                    {"i": appointment_id},
                )
            ).scalar()
        return str(row)
    finally:
        await engine.dispose()


async def _count_reminder_events(tenant_id: str) -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM events WHERE tenant_id = :t "
                        "AND type = 'admin.appointment.reminder_due_24h'"
                    ),
                    {"t": tenant_id},
                )
            ).scalar()
        return int(row or 0)
    finally:
        await engine.dispose()


async def test_poll_marks_due_appointment_as_sent_24h(tenant_with_customer):
    tid, cid = tenant_with_customer
    due_at = datetime.now(UTC) + timedelta(hours=24)
    appt_id = await _insert_appointment(tid, cid, scheduled_at=due_at)

    result = await poll_appointment_reminders({})
    assert result["status"] == "ok"
    assert result["sent_24h"] >= 1

    assert await _appointment_reminder_status(appt_id) == "sent_24h"
    assert await _count_reminder_events(tid) == 1


async def test_poll_skips_appointment_outside_24h_window(tenant_with_customer):
    tid, cid = tenant_with_customer
    far_future = datetime.now(UTC) + timedelta(hours=72)
    appt_id = await _insert_appointment(tid, cid, scheduled_at=far_future)

    result = await poll_appointment_reminders({})
    # Other concurrent tests may bump sent_24h, but THIS appointment must
    # not move because its scheduled_at is well outside the window.
    assert await _appointment_reminder_status(appt_id) == "pending"
    assert await _count_reminder_events(tid) == 0
    assert result["status"] == "ok"


async def test_poll_skips_cancelled_appointment(tenant_with_customer):
    tid, cid = tenant_with_customer
    due_at = datetime.now(UTC) + timedelta(hours=24)
    appt_id = await _insert_appointment(tid, cid, scheduled_at=due_at, status="cancelled")

    await poll_appointment_reminders({})

    assert await _appointment_reminder_status(appt_id) == "pending"
    assert await _count_reminder_events(tid) == 0


async def test_poll_is_idempotent_within_same_minute(tenant_with_customer):
    """A second poll within the same minute must not re-fire the same
    reminder. Once `reminder_status` is `sent_24h`, the SELECT predicate
    excludes the row."""
    tid, cid = tenant_with_customer
    due_at = datetime.now(UTC) + timedelta(hours=24)
    appt_id = await _insert_appointment(tid, cid, scheduled_at=due_at)

    await poll_appointment_reminders({})
    first_count = await _count_reminder_events(tid)
    await poll_appointment_reminders({})
    second_count = await _count_reminder_events(tid)

    assert first_count == 1
    assert second_count == 1, "second tick must be a no-op"
    assert await _appointment_reminder_status(appt_id) == "sent_24h"

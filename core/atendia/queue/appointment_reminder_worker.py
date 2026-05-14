"""Sprint B.4 — appointment reminder scheduler.

Runs once per minute via arq's ``cron_jobs``. Picks appointments
scheduled ~24h ahead whose ``reminder_status`` is still ``pending``,
marks them ``sent_24h``, and emits an ``admin.appointment.reminder_due_24h``
event so audit + analytics see the auto-dispatch.

Actual WhatsApp delivery still routes through ``messaging.send_reminder``
(provider abstraction) — Demo + Empty today, real Meta when a real
provider lands. Emitting the event decouples scheduling from delivery so
this worker doesn't have to know the channel.

Hardening pattern matches ``followup_worker``:

* SELECT FOR UPDATE SKIP LOCKED so concurrent workers don't double-fire.
* `LIMIT _RATE_CAP_PER_TICK` so a backlog never spams Meta.
* `status NOT IN ('cancelled', 'completed', 'no_show')` so closed
  appointments don't get reminders.
* `reminder_status = 'pending'` so a re-tick within the same minute is
  idempotent — once flipped to `sent_24h` the row no longer matches.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings

logger = logging.getLogger(__name__)

# Window half-width — ±5min around (now + 24h) so a poll every minute
# always catches each appointment exactly once. 5min is generous enough
# to absorb a missed tick without losing the reminder.
_WINDOW_HALF_WIDTH = timedelta(minutes=5)

# Hard cap per tick so a sudden backlog (e.g. cron paused for an hour)
# doesn't dispatch hundreds at once and trip Meta's rate limit.
_RATE_CAP_PER_TICK = 50

# Reminder statuses the picker considers "still owed".
_PENDING_STATUSES = {"pending"}


async def poll_appointment_reminders(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq cron entry point. Returns a small status dict for observability."""
    settings = get_settings()
    now = datetime.now(UTC)
    target = now + timedelta(hours=24)
    window_start = target - _WINDOW_HALF_WIDTH
    window_end = target + _WINDOW_HALF_WIDTH

    engine = create_async_engine(settings.database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    sent = 0

    try:
        async with sessionmaker() as session:
            async with session.begin():
                due = (
                    (
                        await session.execute(
                            text(
                                "SELECT id, tenant_id, customer_id, scheduled_at, service "
                                "FROM appointments "
                                "WHERE deleted_at IS NULL "
                                "  AND status IN ('scheduled', 'confirmed') "
                                "  AND reminder_status = 'pending' "
                                "  AND scheduled_at >= :ws "
                                "  AND scheduled_at <= :we "
                                "FOR UPDATE SKIP LOCKED "
                                "LIMIT :lim"
                            ),
                            {
                                "ws": window_start,
                                "we": window_end,
                                "lim": _RATE_CAP_PER_TICK,
                            },
                        )
                    )
                    .mappings()
                    .all()
                )

                for row in due:
                    await session.execute(
                        text(
                            "UPDATE appointments "
                            "SET reminder_status = 'sent_24h', "
                            "    reminder_last_sent_at = :n, "
                            "    updated_at = :n "
                            "WHERE id = :i"
                        ),
                        {"n": now, "i": row["id"]},
                    )
                    await session.execute(
                        text(
                            "INSERT INTO events "
                            "(id, tenant_id, type, payload, occurred_at) "
                            "VALUES (:eid, :t, "
                            "  'admin.appointment.reminder_due_24h', "
                            "  CAST(:p AS jsonb), :n)"
                        ),
                        {
                            "eid": uuid4(),
                            "t": row["tenant_id"],
                            "p": json.dumps(
                                {
                                    "appointment_id": str(row["id"]),
                                    "customer_id": str(row["customer_id"]),
                                    "scheduled_at": row["scheduled_at"].isoformat(),
                                    "service": row["service"],
                                    "kind": "24h",
                                }
                            ),
                            "n": now,
                        },
                    )
                    sent += 1
    finally:
        await engine.dispose()

    if sent:
        logger.info(
            "appointment_reminder_worker: dispatched %d reminder(s) in window [%s, %s]",
            sent,
            window_start.isoformat(),
            window_end.isoformat(),
        )
    return {"status": "ok", "sent_24h": sent}

"""Cron worker that fires due Phase 3d follow-ups.

Runs once a minute via arq's `cron_jobs`. Picks rows from
`followups_scheduled` where `run_at <= now()` AND `status = 'pending'`
AND not cancelled AND not in flight, with `SELECT FOR UPDATE SKIP LOCKED`
so two workers can run side-by-side without stepping on each other.

Hardening (per code-review):
  * `enqueued_at` set BEFORE arq enqueue — if the worker dies between
    enqueue and status='sent', the row is treated as in-flight and won't
    be re-picked by the next tick (idempotency on restarts).
  * Re-check `cancelled_at IS NULL` inside the SELECT FOR UPDATE txn
    so a customer who replies between cron pick and enqueue wins the race.
  * `LIMIT 50` per tick — prevents thundering-herd on Meta when 1k
    conversations all hit 3h at once. Trailing rows pick up next minute.
  * Quiet hours: server-time hour ∉ [4, 13] UTC ≈ ∉ [22, 7] America/Mexico_City.
    Crude but better than 3am pings; per-customer TZ is Phase 3d.2 work.
  * `tenants.followups_enabled` join — kill switch per tenant.
  * On 3h fire: cancel the same conversation's pending 12h and re-arm
    a fresh 12h from now — keeps the silence clock anchored to the most
    recent outbound (the follow-up itself).
"""
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.queue.enqueue import enqueue_outbound
from atendia.runner.followup_scheduler import render_followup_body


# Server-time UTC hours where firing follow-ups is suppressed. 04-13 UTC
# ≈ 22:00–07:00 America/Mexico_City — the crudely-named quiet window for
# the Mexican deployment. Tenants in other geos need a per-tenant override
# (Phase 3d.2).
_QUIET_HOURS_UTC: frozenset[int] = frozenset({4, 5, 6, 7, 8, 9, 10, 11, 12, 13})

# Hard cap on follow-ups dispatched per cron tick. arq + Meta both have
# rate ceilings; trailing rows just wait one more minute.
_RATE_CAP_PER_TICK: int = 50


def _quiet_hours_active(now: datetime) -> bool:
    return now.hour in _QUIET_HOURS_UTC


async def _pick_due_followups(
    session: AsyncSession, *, now: datetime, limit: int,
) -> list[dict[str, Any]]:
    """Lock + return up to `limit` due follow-up rows.

    SKIP LOCKED keeps multiple workers harmless. The IS NULL guards on
    cancelled_at + enqueued_at do the idempotency + cancellation
    re-check inside the same lock window.
    """
    rows = (await session.execute(
        text(
            "SELECT f.id, f.conversation_id, f.tenant_id, f.kind, f.attempts "
            "FROM followups_scheduled f "
            "JOIN tenants t ON t.id = f.tenant_id "
            "WHERE f.status = 'pending' "
            "  AND f.cancelled_at IS NULL "
            "  AND f.enqueued_at IS NULL "
            "  AND f.run_at <= :now "
            "  AND t.followups_enabled = true "
            "ORDER BY f.run_at "
            "LIMIT :lim "
            "FOR UPDATE SKIP LOCKED"
        ),
        {"now": now, "lim": limit},
    )).fetchall()
    return [
        {"id": r[0], "conversation_id": r[1], "tenant_id": r[2],
         "kind": r[3], "attempts": r[4]}
        for r in rows
    ]


async def _load_extracted_data(
    session: AsyncSession, conversation_id: Any,
) -> dict:
    row = (await session.execute(
        text("SELECT extracted_data FROM conversation_state "
             "WHERE conversation_id = :c"),
        {"c": conversation_id},
    )).fetchone()
    if not row or not row[0]:
        return {}
    return dict(row[0])


async def _load_recipient_phone(
    session: AsyncSession, conversation_id: Any,
) -> str | None:
    row = (await session.execute(
        text("SELECT cu.phone_e164 "
             "FROM conversations c "
             "JOIN customers cu ON cu.id = c.customer_id "
             "WHERE c.id = :c"),
        {"c": conversation_id},
    )).fetchone()
    return row[0] if row else None


async def _mark_in_flight(
    session: AsyncSession, *, followup_id: Any, now: datetime,
) -> None:
    await session.execute(
        text("UPDATE followups_scheduled SET enqueued_at = :now "
             "WHERE id = :fid"),
        {"now": now, "fid": followup_id},
    )


async def _mark_sent(
    session: AsyncSession, *, followup_id: Any, conversation_id: Any,
) -> None:
    await session.execute(
        text("UPDATE followups_scheduled SET status = 'sent' WHERE id = :fid"),
        {"fid": followup_id},
    )
    await session.execute(
        text("UPDATE conversation_state "
             "SET followups_sent_count = followups_sent_count + 1 "
             "WHERE conversation_id = :c"),
        {"c": conversation_id},
    )


async def _mark_failed(
    session: AsyncSession, *, followup_id: Any, error: str,
) -> None:
    await session.execute(
        text("UPDATE followups_scheduled "
             "SET status = 'failed', last_error = :err, "
             "    attempts = attempts + 1 "
             "WHERE id = :fid"),
        {"err": error[:500], "fid": followup_id},
    )


async def _reschedule_12h_from_now(
    session: AsyncSession, *, conversation_id: Any, tenant_id: Any, now: datetime,
) -> None:
    """When a 3h fires, the silence clock should restart — cancel the
    pending 12h (originally anchored to the previous outbound) and re-arm
    a fresh one from THIS follow-up's send time."""
    await session.execute(
        text("UPDATE followups_scheduled "
             "SET status = 'cancelled', cancelled_at = :now "
             "WHERE conversation_id = :c "
             "  AND kind = '12h_silence' "
             "  AND status = 'pending' "
             "  AND cancelled_at IS NULL"),
        {"now": now, "c": conversation_id},
    )
    new_run_at = now + timedelta(hours=12)
    await session.execute(
        text("INSERT INTO followups_scheduled "
             "(conversation_id, tenant_id, run_at, status, kind) "
             "VALUES (:c, :t, :ra, 'pending', '12h_silence')"),
        {"c": conversation_id, "t": tenant_id, "ra": new_run_at},
    )


async def poll_followups(ctx: dict) -> dict:
    """arq cron entry point. Returns a small status dict for observability.

    The function is structured so each follow-up is enqueued in its own
    sub-transaction. A failure on one row doesn't lose the lock on other
    rows in the same tick.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    if _quiet_hours_active(now):
        return {"status": "skipped_quiet_hours", "hour_utc": now.hour}

    arq_redis = ctx.get("redis")
    if arq_redis is None:
        return {"status": "skipped_no_redis"}

    engine = create_async_engine(settings.database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    sent = 0
    failed = 0
    skipped_no_phone = 0

    try:
        async with sessionmaker() as session:
            async with session.begin():
                due = await _pick_due_followups(
                    session, now=now, limit=_RATE_CAP_PER_TICK,
                )
                # Mark every picked row as in-flight before releasing the
                # lock. We do this inside the same txn so the SKIP LOCKED
                # contract holds: another worker picking up immediately
                # after still sees enqueued_at IS NOT NULL and skips.
                for f in due:
                    await _mark_in_flight(
                        session, followup_id=f["id"], now=now,
                    )

            # Each follow-up: render + enqueue + status-update in its own txn.
            for f in due:
                try:
                    async with sessionmaker() as send_session:
                        async with send_session.begin():
                            extracted = await _load_extracted_data(
                                send_session, f["conversation_id"],
                            )
                            phone = await _load_recipient_phone(
                                send_session, f["conversation_id"],
                            )
                            if not phone:
                                # Customer row vanished — mark failed, move on.
                                await _mark_failed(
                                    send_session, followup_id=f["id"],
                                    error="recipient_phone_missing",
                                )
                                skipped_no_phone += 1
                                continue

                            body = render_followup_body(
                                kind=f["kind"], extracted_data=extracted,
                            )
                            from atendia.channels.base import OutboundMessage
                            from uuid import uuid4
                            outbound = OutboundMessage(
                                tenant_id=str(f["tenant_id"]),
                                to_phone_e164=phone,
                                text=body,
                                idempotency_key=f"followup-{f['id']}-{uuid4()}",
                            )
                            await enqueue_outbound(arq_redis, outbound)
                            await _mark_sent(
                                send_session,
                                followup_id=f["id"],
                                conversation_id=f["conversation_id"],
                            )

                            if f["kind"] == "3h_silence":
                                await _reschedule_12h_from_now(
                                    send_session,
                                    conversation_id=f["conversation_id"],
                                    tenant_id=f["tenant_id"],
                                    now=now,
                                )
                    sent += 1
                except Exception as exc:  # noqa: BLE001 — fail one row, keep ticking
                    failed += 1
                    async with sessionmaker() as err_session:
                        async with err_session.begin():
                            await _mark_failed(
                                err_session, followup_id=f["id"],
                                error=f"{type(exc).__name__}: {exc}",
                            )
    finally:
        await engine.dispose()

    return {
        "status": "ok", "picked": len(due),
        "sent": sent, "failed": failed,
        "skipped_no_phone": skipped_no_phone,
    }

"""Schedule + cancel + render Phase 3d follow-up reminders.

Two-tier ladder: 3h ('camión vs moto' reframe) and 12h ('sigues en pie?'
re-engagement) after the bot's outbound. Both fire INSIDE the 24h
WhatsApp customer-initiated window so plain text works — Meta-approved
templates for >24h follow-ups are Phase 3d.2 work.

Lifecycle:
  outbound turn ends -> schedule_followups_after_outbound() inserts two
                        rows in followups_scheduled (kind=3h_silence,
                        12h_silence) with run_at = now()+3h / +12h.
  inbound arrives    -> cancel_pending_followups() flips status=cancelled
                        on every pending row for that conversation.
                        Also runs in the runner before flow_router so the
                        binary-confirmation handler doesn't rebound.
  cron tick fires    -> followup_worker.poll_followups() picks due rows
                        with SKIP LOCKED, re-checks cancellation, renders
                        the body using LIVE extracted_data, enqueues
                        outbound, marks status=sent.
"""

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Spec from v1 prompt: only two tiers in the in-window scope.
FOLLOWUP_KINDS: Final[tuple[str, ...]] = ("3h_silence", "12h_silence")
_DELAYS: Final[dict[str, timedelta]] = {
    "3h_silence": timedelta(hours=3),
    "12h_silence": timedelta(hours=12),
}


async def schedule_followups_after_outbound(
    *,
    session: AsyncSession,
    conversation_id: UUID,
    tenant_id: UUID,
    extracted_snapshot: dict,
) -> None:
    """Insert 3h + 12h pending followups for this turn's outbound.

    Caller is expected to have just enqueued an outbound message — there's
    no point scheduling a re-engagement if nothing went out.

    `extracted_snapshot` is stored as audit context only (read in
    operator dashboard / future analytics). The cron worker uses live
    extracted_data at fire time — see followup_worker._render_body.

    Idempotency: if rows of the same kind already exist for this
    conversation in 'pending', they're left alone. Reach: each outbound
    turn restarts the silence clock — see the 'reschedule on 3h fire'
    behaviour in followup_worker.poll_followups.
    """
    now = datetime.now(UTC)
    for kind in FOLLOWUP_KINDS:
        run_at = now + _DELAYS[kind]
        await session.execute(
            text(
                "INSERT INTO followups_scheduled "
                "(conversation_id, tenant_id, run_at, status, kind, context) "
                "SELECT :cid, :tid, :ra, 'pending', "
                "       CAST(:k AS VARCHAR), CAST(:ctx AS JSONB) "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM followups_scheduled "
                "  WHERE conversation_id = :cid "
                "    AND kind = CAST(:k AS VARCHAR) "
                "    AND status = 'pending' "
                "    AND cancelled_at IS NULL"
                ")"
            ),
            {
                "cid": conversation_id,
                "tid": tenant_id,
                "ra": run_at,
                "k": kind,
                "ctx": __import__("json").dumps(extracted_snapshot),
            },
        )


async def cancel_pending_followups(
    *,
    session: AsyncSession,
    conversation_id: UUID,
) -> int:
    """Mark every pending follow-up for this conversation as cancelled.

    Called when an inbound arrives — the customer is engaged again, so the
    silence-based premise is invalidated. Returns the row count cancelled
    so callers can emit observability events if they care.

    The cron worker re-checks `cancelled_at IS NULL` inside its
    SELECT FOR UPDATE txn, so a cancellation that lands between cron
    pick and enqueue still wins.
    """
    result = await session.execute(
        text(
            "UPDATE followups_scheduled "
            "SET status = 'cancelled', cancelled_at = :now "
            "WHERE conversation_id = :cid "
            "  AND status = 'pending' "
            "  AND cancelled_at IS NULL"
        ),
        {"cid": conversation_id, "now": datetime.now(UTC)},
    )
    return result.rowcount or 0


def render_followup_body(
    *,
    kind: str,
    extracted_data: dict,
) -> str:
    """Render the v1-prompt copy with live extracted_data.

    `extracted_data` shape: {field_name: {value, confidence, source_turn}}
    or {field_name: value} — accept both for robustness.

    The bodies match the v1 master prompt verbatim where it specifies
    them; falls back to a generic line on unknown kinds so a misconfigured
    cron job degrades gracefully instead of blowing up.
    """

    def _val(name: str, default: str) -> str:
        v = extracted_data.get(name)
        if isinstance(v, dict):
            v = v.get("value")
        return str(v) if v else default

    if kind == "3h_silence":
        return (
            "En lugar de gastar en el camión, puedes invertirlo mejor en "
            "tu moto. Aquí estoy para ayudarte con eso."
        )
    if kind == "12h_silence":
        modelo = _val("modelo_moto", "moto")
        plan = _val("plan_credito", "")
        plan_part = f" Tu plan {plan} sigue activo." if plan else ""
        return f"Hola, ¿sigues en pie con tu {modelo}?{plan_part} El único paso que falta eres tú."
    # Defensive default — a misconfigured kind shouldn't crash the worker.
    return "Hola, ¿seguimos con tu trámite? Aquí estoy si necesitas ayuda."

"""Build + persist HandoffSummary for human escalations (Phase 3c.2 / T24).

The runner has multiple sites that escalate (outside_24h_window,
composer_failed, future: composer's `suggested_handoff` markers). All of
them need to drop the same shaped payload onto `human_handoffs.payload`
JSONB so the operator dashboard can render context without parsing
free-text reasons.

`build_handoff_summary` snapshots ExtractedFields + the doc-progress
matrix into a HandoffSummary. `persist_handoff` is a single chokepoint
the runner uses so we don't drift between sites — every escalation
goes through this function or it's a bug.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.extracted_fields import ExtractedFields
from atendia.contracts.handoff_summary import HandoffReason, HandoffSummary
from atendia.state_machine.derived import funnel_stage


def build_handoff_summary(
    *,
    reason: HandoffReason,
    extracted: ExtractedFields,
    last_inbound_text: str,
    suggested_next_action: str,
    docs_per_plan: dict[str, list[str]],
) -> HandoffSummary:
    """Snapshot of extracted state at the moment of handoff.

    `docs_per_plan` is the tenant-specific catalog of required docs per
    tipo_credito (e.g. "Nómina Tarjeta" -> ["ine", "comprobante", ...]).
    Empty dict is fine — docs_recibidos / docs_pendientes will both be empty.
    """
    docs_received: list[str] = []
    docs_pending: list[str] = []
    if extracted.tipo_credito:
        plan_label = extracted.tipo_credito.value
        for doc in docs_per_plan.get(plan_label, []):
            if getattr(extracted, f"docs_{doc}", False):
                docs_received.append(doc)
            else:
                docs_pending.append(doc)

    enganche_estimado: str | None = None
    if extracted.plan_credito:
        # Lightweight summary; the runner can plug in the real number from
        # action_payload when a quote was just produced. For now, just the
        # percentage so the human agent doesn't start from zero.
        enganche_estimado = f"{extracted.plan_credito.value} de enganche"

    return HandoffSummary(
        reason=reason,
        nombre=extracted.nombre,
        modelo_moto=extracted.modelo_moto,
        plan_credito=extracted.plan_credito.value if extracted.plan_credito else None,
        enganche_estimado=enganche_estimado,
        docs_recibidos=docs_received,
        docs_pendientes=docs_pending,
        last_inbound_message=last_inbound_text,
        suggested_next_action=suggested_next_action,
        funnel_stage=funnel_stage(extracted),
        cita_dia=extracted.cita_dia,
    )


async def persist_handoff(
    *,
    session: AsyncSession,
    conversation_id: UUID,
    tenant_id: UUID,
    summary: HandoffSummary,
) -> None:
    """Insert a row into human_handoffs with the structured payload.

    Single chokepoint for every handoff site in the runner — keeps the
    `payload` column populated everywhere instead of just where the dev
    happened to remember.
    """
    await session.execute(
        text(
            "INSERT INTO human_handoffs "
            "(conversation_id, tenant_id, reason, status, payload) "
            "VALUES (:cid, :tid, :r, 'pending', CAST(:p AS JSONB))"
        ),
        {
            "cid": conversation_id,
            "tid": tenant_id,
            "r": summary.reason.value,
            "p": summary.model_dump_json(),
        },
    )

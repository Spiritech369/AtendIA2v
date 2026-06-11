"""Phase 20 — Single-contact smoke policy (runtime-enforced).

Everything that decides whether a validated Respond-Style turn may become a
VISIBLE WhatsApp send lives here, evaluated per turn from deployment
metadata. Nothing is prompt-trusted: the allowlist, the scope, the approval
text and the preflight marker are all checked in code, every turn.

The default state of every flag is OFF: with no metadata changes this module
is a no-op and the direct route stays shadow/no-send.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

SMOKE_SOURCE = "respond_style_single_contact_smoke"
APPROVED_SCOPE = "approved_contact_only"

# Literal human approval text from the Phase 19 packet (section 13). The
# deployment metadata must carry EXACTLY this text for sends to be possible.
EXACT_APPROVAL_TEXT = (
    "Apruebo activar controlled single-contact smoke Respond-Style "
    "únicamente para el teléfono 8128889241, con "
    "send_scope=approved_contact_only, sin workflows/actions reales, sin "
    "canary, sin production, con rollback inmediato ante cualquier criterio "
    "de falla."
)

FORBIDDEN_SCOPES = ("all", "all_contacts", "tenant", "canary", "production", "live")


@dataclass(frozen=True)
class SmokeEvaluation:
    """Outcome of the per-turn smoke policy check."""

    active: bool
    allowed: bool
    pause_after_send: bool = False
    scope: str | None = None
    phone_normalized: str | None = None
    reasons: list[str] = field(default_factory=list)


def _fold_phone(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _fold_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def smoke_flags_active(metadata: dict[str, Any] | None) -> bool:
    return bool((metadata or {}).get("respond_style_live_send_enabled") is True)


def phone_in_smoke_allowlist(
    metadata: dict[str, Any] | None, phone: str | None
) -> bool:
    allowed = (metadata or {}).get("respond_style_live_allowed_phones")
    if not isinstance(allowed, list) or not allowed or not phone:
        return False
    folded = _fold_phone(phone)
    return bool(folded) and any(_fold_phone(item) == folded for item in allowed)


def legacy_send_suppressed_for_smoke(
    metadata: dict[str, Any] | None, phone: str | None
) -> bool:
    """Legacy customer copy is suppressed ONLY while smoke is active AND only
    for the allowlisted phone. Every other contact is untouched."""
    return smoke_flags_active(metadata) and phone_in_smoke_allowlist(metadata, phone)


def evaluate_smoke_send(
    *,
    metadata: dict[str, Any] | None,
    from_phone: str | None,
    result: Any,
    takeover_pending: bool,
) -> SmokeEvaluation:
    """Runtime gate for a single turn. ``result`` is the
    ProductAgentRuntimeResult of the validated direct-route turn."""
    meta = metadata or {}
    if not smoke_flags_active(meta):
        return SmokeEvaluation(active=False, allowed=False, reasons=["smoke_inactive"])

    reasons: list[str] = []
    scope = str(meta.get("respond_style_send_scope") or "")
    if scope != APPROVED_SCOPE or scope in FORBIDDEN_SCOPES:
        reasons.append("send_scope_unsafe")
    if not phone_in_smoke_allowlist(meta, from_phone):
        reasons.append("phone_not_allowlisted")
    if meta.get("respond_style_workflows_enabled") is True:
        reasons.append("workflows_must_be_disabled")
    if meta.get("respond_style_actions_enabled") is True:
        reasons.append("actions_must_be_disabled")
    if meta.get("respond_style_legacy_fallback_enabled") is True:
        reasons.append("legacy_fallback_must_be_disabled")
    if meta.get("respond_style_fail_closed_notify_operator") is not True:
        reasons.append("fail_closed_notify_operator_required")
    if meta.get("respond_style_rollback_active") is True:
        reasons.append("rollback_active")
    if _fold_text(meta.get("respond_style_smoke_approval_text")) != _fold_text(
        EXACT_APPROVAL_TEXT
    ):
        reasons.append("approval_text_missing_or_inexact")
    if not meta.get("respond_style_preflight_passed_at"):
        reasons.append("preflight_not_passed")

    if takeover_pending:
        reasons.append("human_takeover_pending")

    pause_after_send = False
    if result is None:
        reasons.append("no_runtime_result")
    else:
        validation = getattr(result, "validation_result", None) or {}
        status = (
            validation.get("status") if isinstance(validation, dict) else None
        )
        if status != "valid":
            reasons.append("validator_not_passed")
        if getattr(result, "blocked_reason", None):
            reasons.append("turn_blocked")
        if not (getattr(result, "final_message", None) or "").strip():
            reasons.append("final_message_missing")
        if getattr(result, "workflow_event_proposals", None):
            reasons.append("workflow_proposals_present")
        if getattr(result, "action_proposals", None):
            reasons.append("action_proposals_present")
        side_effects = getattr(result, "side_effects", None) or {}
        if any(side_effects.values()):
            reasons.append("side_effects_present")
        if getattr(result, "handoff_proposal", None):
            # The accepted-handoff ack may be sent ONCE; afterwards the bot
            # pauses until a human takes over (or rollback/reset).
            pause_after_send = True

    return SmokeEvaluation(
        active=True,
        allowed=not reasons,
        pause_after_send=pause_after_send,
        scope=scope,
        phone_normalized=_fold_phone(from_phone),
        reasons=reasons,
    )


async def stage_smoke_send(
    session: Any,
    *,
    tenant_id: str,
    deployment_id: str,
    agent_version_id: str,
    conversation_id: str,
    inbound_message_id: str | None,
    to_phone_e164: str,
    final_message: str,
    model: str | None,
    trace_id: str | None,
    send_scope: str,
    validator_status: str,
    reply_channel: str | None = None,
) -> dict[str, Any]:
    """Stages the validated final_message to the existing outbox path. The
    idempotency key is derived from the inbound message so retries can never
    double-send a turn."""
    from atendia.channels.base import OutboundMessage
    from atendia.queue.outbox import stage_outbound

    smoke_session_id = str(uuid4())
    idempotency_key = (
        f"rs-smoke-{inbound_message_id}" if inbound_message_id else f"rs-smoke-{uuid4()}"
    )
    message = OutboundMessage(
        tenant_id=str(tenant_id),
        to_phone_e164=to_phone_e164,
        text=final_message,
        idempotency_key=idempotency_key,
        metadata={
            "source": SMOKE_SOURCE,
            "deployment_id": str(deployment_id),
            "agent_version_id": str(agent_version_id),
            "conversation_id": str(conversation_id),
            "inbound_message_id": str(inbound_message_id) if inbound_message_id else None,
            "phone_normalized": _fold_phone(to_phone_e164),
            "send_scope": send_scope,
            "model": model,
            "trace_id": str(trace_id) if trace_id else None,
            "smoke_session_id": smoke_session_id,
            "validator_status": validator_status,
            # Transport routing: the worker sends via Baileys only when the
            # outbound carries the same channel the inbound arrived on.
            "reply_channel": reply_channel,
        },
    )
    outbox_id = await stage_outbound(session, message)
    logger.info(
        "respond_style_smoke_send_staged outbox=%s conversation=%s",
        outbox_id,
        conversation_id,
    )
    return {
        "staged": True,
        "outbox_id": str(outbox_id),
        "smoke_session_id": smoke_session_id,
        "idempotency_key": idempotency_key,
        "source": SMOKE_SOURCE,
    }


async def notify_operator_fail_closed(
    session: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    reason: str,
    detail: dict[str, Any] | None = None,
) -> str:
    """15B in the wild: a blocked smoke turn must page a human, never leave
    the customer in dead air with no one knowing."""
    from atendia.db.models.lifecycle import HumanHandoff

    row = HumanHandoff(
        conversation_id=UUID(str(conversation_id)),
        tenant_id=UUID(str(tenant_id)),
        reason=f"respond_style_smoke_fail_closed: {reason}"[:500],
        payload={
            "source": "respond_style_smoke_fail_closed",
            "internal_attention_needed": True,
            "customer_copy_sent": False,
            **(detail or {}),
        },
        status="open",
    )
    session.add(row)
    await session.flush()
    return str(row.id)


async def get_takeover_pending(session: Any, *, conversation_id: str) -> bool:
    from atendia.db.models.product_agent import RespondStyleShadowFields

    row = await session.get(RespondStyleShadowFields, UUID(str(conversation_id)))
    return bool(row is not None and getattr(row, "takeover_pending", False))


async def set_takeover_pending(
    session: Any,
    *,
    tenant_id: str,
    conversation_id: str,
) -> None:
    from atendia.db.models.product_agent import RespondStyleShadowFields

    row = await session.get(RespondStyleShadowFields, UUID(str(conversation_id)))
    if row is None:
        row = RespondStyleShadowFields(
            conversation_id=UUID(str(conversation_id)),
            tenant_id=UUID(str(tenant_id)),
            field_values={},
            audit_log=[],
        )
        session.add(row)
    row.takeover_pending = True
    await session.flush()


__all__ = [
    "APPROVED_SCOPE",
    "EXACT_APPROVAL_TEXT",
    "SMOKE_SOURCE",
    "SmokeEvaluation",
    "evaluate_smoke_send",
    "get_takeover_pending",
    "legacy_send_suppressed_for_smoke",
    "notify_operator_fail_closed",
    "phone_in_smoke_allowlist",
    "set_takeover_pending",
    "smoke_flags_active",
    "stage_smoke_send",
]

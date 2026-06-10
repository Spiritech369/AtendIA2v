from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PreparedSendStatus = Literal["blocked", "prepared"]


class PreparedSendDecision(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: PreparedSendStatus
    allowed: bool = False
    dry_run: bool = True
    reason: str
    reasons: list[str] = Field(default_factory=list)
    send_scope: str | None = None
    contact_id: str | None = None
    phone_e164: str | None = None
    allowed_contact_ids: list[str] = Field(default_factory=list)
    allowed_test_phones: list[str] = Field(default_factory=list)
    provider_fallback_blocked: bool = False
    whatsapp_send_attempted: bool = False
    outbox_write_attempted: bool = False


def evaluate_prepared_send_policy(
    *,
    runtime_config: Mapping[str, Any],
    global_send_enabled: bool,
    contact_id: str | None,
    phone_e164: str | None,
    provider_fallback_detected: bool = False,
) -> PreparedSendDecision:
    """Evaluate whether a runtime v2 turn may reach prepared-send state.

    This policy never writes outbox rows and never sends WhatsApp. It only
    records whether a future send would pass tenant/contact gates.
    """

    reasons: list[str] = []
    if not _truthy(runtime_config.get("runtime_v2_enabled")):
        reasons.append("runtime_v2_enabled_false")
    if not global_send_enabled:
        reasons.append("global_send_disabled")
    if not _truthy(runtime_config.get("send_enabled")):
        reasons.append("tenant_send_disabled")
    if not _truthy(runtime_config.get("outbox_enabled")):
        reasons.append("tenant_outbox_disabled")
    if not _truthy(runtime_config.get("single_contact_smoke_enabled")):
        reasons.append("single_contact_smoke_disabled")
    if _truthy(runtime_config.get("tenant_domain_contract_safe_mode")):
        reasons.append("tenant_domain_contract_safe_mode")

    send_scope = _text(runtime_config.get("send_scope")) or None
    if send_scope != "approved_contact_only":
        reasons.append("send_scope_not_approved_contact_only")

    allowed_contact_ids = _string_list(runtime_config.get("allowed_contact_ids"))
    allowed_test_phones = _string_list(runtime_config.get("allowed_test_phones"))
    if not allowed_contact_ids and not allowed_test_phones:
        reasons.append("approved_contact_allowlist_missing")
    if len(allowed_contact_ids) > 1 or len(allowed_test_phones) > 1:
        reasons.append("single_contact_smoke_requires_exactly_one_allowed_contact")

    contact_allowed = bool(contact_id and str(contact_id) in set(allowed_contact_ids))
    phone_allowed = bool(phone_e164 and str(phone_e164) in set(allowed_test_phones))
    if not contact_allowed and not phone_allowed:
        reasons.append("contact_not_approved_for_single_contact_smoke")

    provider_fallback_blocked = bool(provider_fallback_detected)
    if provider_fallback_blocked:
        reasons.append("provider_fallback_blocks_visible_send")

    if reasons:
        return PreparedSendDecision(
            status="blocked",
            allowed=False,
            reason=reasons[0],
            reasons=reasons,
            send_scope=send_scope,
            contact_id=str(contact_id) if contact_id else None,
            phone_e164=str(phone_e164) if phone_e164 else None,
            allowed_contact_ids=allowed_contact_ids,
            allowed_test_phones=allowed_test_phones,
            provider_fallback_blocked=provider_fallback_blocked,
        )

    return PreparedSendDecision(
        status="prepared",
        allowed=True,
        reason="prepared_send_allowed_by_single_contact_policy",
        reasons=["prepared_send_allowed_by_single_contact_policy"],
        send_scope=send_scope,
        contact_id=str(contact_id) if contact_id else None,
        phone_e164=str(phone_e164) if phone_e164 else None,
        allowed_contact_ids=allowed_contact_ids,
        allowed_test_phones=allowed_test_phones,
        provider_fallback_blocked=False,
    )


def provider_fallback_detected_from_trace(trace_metadata: Mapping[str, Any]) -> bool:
    if _text(trace_metadata.get("fallback")):
        return True
    if _has_human_review_provider_note(trace_metadata.get("human_review_notes")):
        return True
    reliability = trace_metadata.get("provider_reliability")
    if isinstance(reliability, Mapping):
        for value in reliability.values():
            if isinstance(value, Mapping) and _truthy(value.get("fallback_used")):
                return True
    return False


def legacy_visible_output_allowed(*, runtime_v2_enabled: bool) -> bool:
    return not bool(runtime_v2_enabled)


def legacy_visible_output_block_trace(reason: str = "runtime_v2_enabled") -> dict[str, Any]:
    return {
        "event": "legacy_visible_output_blocked",
        "reason": reason,
        "send_status": "no_send",
        "legacy_fallback_used": False,
        "customer_visible_message_sent": False,
    }


def _has_human_review_provider_note(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    return any("provider_error" in str(item) for item in value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


__all__ = [
    "PreparedSendDecision",
    "evaluate_prepared_send_policy",
    "legacy_visible_output_allowed",
    "legacy_visible_output_block_trace",
    "provider_fallback_detected_from_trace",
]

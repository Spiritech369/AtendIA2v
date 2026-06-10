from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.schemas import TurnOutput
from atendia.agent_runtime.send_policy import (
    PreparedSendDecision,
    evaluate_prepared_send_policy,
)
from atendia.runner.outbound_dispatcher import enqueue_messages

SendMode = Literal["no_send", "live_candidate"]


class SendAdapterResult(BaseModel):
    mode: SendMode
    send_decision: PreparedSendDecision
    delivery_status: dict[str, str]
    outbox_ids: list[str] = Field(default_factory=list)
    outbound_messages: list[str] | None = None
    outbox_write_attempted: bool = False
    errors: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeV2SendAdapter:
    async def apply(
        self,
        *,
        mode: SendMode,
        session: AsyncSession,
        runtime_config: dict[str, Any],
        global_send_enabled: bool,
        tenant_id: str,
        conversation_id: str,
        turn_number: int,
        contact_id: str | None,
        phone_e164: str | None,
        recipient_phone_e164: str | None,
        output: TurnOutput | None,
        provider_fallback_detected: bool,
    ) -> SendAdapterResult:
        if mode == "no_send":
            send_decision = evaluate_prepared_send_policy(
                runtime_config={**runtime_config, "send_enabled": False},
                global_send_enabled=False,
                contact_id=contact_id,
                phone_e164=phone_e164,
                provider_fallback_detected=provider_fallback_detected,
            )
            return SendAdapterResult(
                mode=mode,
                send_decision=send_decision,
                delivery_status={
                    "send_status": "no_send",
                    "reason": "no_send_mode",
                    "internal_event": "runtime_v2_no_send_mode",
                },
            )

        send_decision = evaluate_prepared_send_policy(
            runtime_config=runtime_config,
            global_send_enabled=global_send_enabled,
            contact_id=contact_id,
            phone_e164=phone_e164,
            provider_fallback_detected=provider_fallback_detected,
        )
        errors: list[dict[str, Any]] = []
        if output is None:
            return SendAdapterResult(
                mode=mode,
                send_decision=send_decision,
                delivery_status={
                    "send_status": "no_send",
                    "reason": "runtime_v2_failed_closed",
                    "internal_event": "runtime_v2_no_send",
                },
                errors=errors,
            )
        if not send_decision.allowed:
            errors.append(
                {
                    "where": "agent_runtime_v2_send_policy",
                    "code": "send_blocked_by_policy",
                    "reason": send_decision.reason,
                    "reasons": list(send_decision.reasons),
                }
            )
            return SendAdapterResult(
                mode=mode,
                send_decision=send_decision,
                delivery_status=_delivery_status(
                    provider_fallback=provider_fallback_detected,
                    send_decision=send_decision.model_dump(mode="json"),
                ),
                errors=errors,
            )
        if not output.final_message:
            errors.append(
                {
                    "where": "agent_runtime_v2_send_path",
                    "code": "final_message_missing",
                    "reason": "prepared_send_allowed_but_final_message_empty",
                }
            )
            return SendAdapterResult(
                mode=mode,
                send_decision=send_decision,
                delivery_status=_delivery_status(
                    provider_fallback=provider_fallback_detected,
                    send_decision=send_decision.model_dump(mode="json"),
                ),
                errors=errors,
            )
        recipient = recipient_phone_e164 or phone_e164
        if not recipient:
            errors.append(
                {
                    "where": "agent_runtime_v2_send_path",
                    "code": "recipient_phone_missing",
                    "reason": "prepared_send_allowed_but_no_recipient_phone",
                }
            )
            return SendAdapterResult(
                mode=mode,
                send_decision=send_decision,
                delivery_status=_delivery_status(
                    provider_fallback=provider_fallback_detected,
                    send_decision=send_decision.model_dump(mode="json"),
                ),
                errors=errors,
            )
        outbox_ids = await enqueue_messages(
            None,
            session=session,
            messages=[output.final_message],
            tenant_id=UUID(str(tenant_id)),
            to_phone_e164=recipient,
            conversation_id=UUID(str(conversation_id)),
            turn_number=turn_number,
            action="agent_runtime_v2_response",
            extra_metadata={
                "source": "agent_runtime_v2",
                "runtime_path": "agent_runtime_v2",
                "reply_channel": "baileys",
                "send_scope": send_decision.send_scope,
                "approved_contact_id": contact_id,
            },
        )
        send_decision.outbox_write_attempted = bool(outbox_ids)
        return SendAdapterResult(
            mode=mode,
            send_decision=send_decision,
            delivery_status=_delivery_status(
                provider_fallback=provider_fallback_detected,
                send_decision=send_decision.model_dump(mode="json"),
            ),
            outbox_ids=outbox_ids,
            outbound_messages=[output.final_message],
            outbox_write_attempted=bool(outbox_ids),
            errors=errors,
        )


def _delivery_status(
    *,
    provider_fallback: bool,
    send_decision: dict[str, Any],
) -> dict[str, str]:
    if provider_fallback:
        return {
            "send_status": "no_send",
            "reason": "provider_fallback_blocks_visible_send",
            "internal_event": "provider_failure_needs_review",
        }
    reasons = [str(item) for item in send_decision.get("reasons", [])]
    if "contact_not_approved_for_single_contact_smoke" in reasons:
        return {
            "send_status": "blocked_contact_not_allowed",
            "reason": "contact_not_approved_for_single_contact_smoke",
            "internal_event": "runtime_v2_send_blocked_by_contact_scope",
        }
    if send_decision.get("allowed") is not True:
        return {
            "send_status": "blocked_by_policy",
            "reason": str(send_decision.get("reason") or "send_blocked_by_policy"),
            "internal_event": "runtime_v2_send_blocked_by_policy",
        }
    return {
        "send_status": "prepared",
        "reason": "prepared_send_allowed_by_single_contact_policy",
        "internal_event": "runtime_v2_prepared_send_preview",
    }

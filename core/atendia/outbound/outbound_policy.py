from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.conversation_control.conversation_status import ConversationControlResult
from atendia.outbound.duplicate_guard import is_duplicate_outbound


class OutboundPolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str | None = None


async def evaluate_outbound_policy(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    control: ConversationControlResult,
    messages: list[str],
    action: str,
    blocked_actions: list[str],
) -> OutboundPolicyResult:
    if not messages:
        return OutboundPolicyResult(allowed=True)
    if not control.bot_allowed:
        return OutboundPolicyResult(allowed=False, reason="bot_not_allowed")
    if control.owner_type in {"human", "team"}:
        return OutboundPolicyResult(allowed=False, reason="owner_not_bot")
    if action in blocked_actions:
        return OutboundPolicyResult(allowed=False, reason="blocked_action")
    if action != "quote" and await is_duplicate_outbound(
        session,
        conversation_id=conversation_id,
        messages=messages,
    ):
        return OutboundPolicyResult(allowed=False, reason="duplicate_outbound")
    return OutboundPolicyResult(allowed=True)


__all__ = ["OutboundPolicyResult", "evaluate_outbound_policy"]

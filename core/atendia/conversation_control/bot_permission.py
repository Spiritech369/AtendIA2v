from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.conversation_control.conversation_status import ConversationControlResult
from atendia.conversation_control.ownership import load_ownership_snapshot


async def evaluate_conversation_control(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    bot_paused: bool,
) -> ConversationControlResult:
    ownership = await load_ownership_snapshot(session, conversation_id=conversation_id)
    if bot_paused:
        return ConversationControlResult(
            bot_allowed=False,
            conversation_status="BOT_PAUSED",
            owner_type="team" if ownership.has_team_owner else "none",
            owner_id=ownership.active_handoff_reason,
            pause_reason=ownership.active_handoff_reason or "bot_paused",
            handoff_required=ownership.has_team_owner,
        )
    if ownership.has_human_owner:
        return ConversationControlResult(
            bot_allowed=False,
            conversation_status="OPEN_HUMAN",
            owner_type="human",
            owner_id=ownership.assigned_user_id,
            pause_reason="human_owner_active",
            handoff_required=False,
        )
    if ownership.has_team_owner:
        return ConversationControlResult(
            bot_allowed=False,
            conversation_status="ESCALATED",
            owner_type="team",
            owner_id=ownership.active_handoff_reason,
            pause_reason=ownership.active_handoff_reason,
            handoff_required=True,
        )
    if ownership.conversation_status == "closed":
        return ConversationControlResult(
            bot_allowed=False,
            conversation_status="CLOSED",
            owner_type="none",
            pause_reason="conversation_closed",
            handoff_required=False,
        )
    return ConversationControlResult(
        bot_allowed=True,
        conversation_status="OPEN_BOT",
        owner_type="bot",
        owner_id=None,
        pause_reason=None,
        handoff_required=False,
    )


__all__ = ["evaluate_conversation_control"]

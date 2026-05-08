"""Operator dashboard — conversation listing + detail.

Phase 4 T14. Tenant-scoped via `current_tenant_id` dep (operator gets JWT
claim, superadmin must pass `?tid=`).

Cursor pagination uses `(last_activity_at DESC, id DESC)` as the stable
sort key. The cursor is base64-url-safe JSON `{"ts": iso, "id": uuid}`.
This is more robust than offset pagination against rows shifting between
pages while the operator scrolls.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.message import MessageRow
from atendia.db.session import get_db_session

router = APIRouter()


# ---------- Response shapes ----------


class ConversationListItem(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    customer_phone: str
    customer_name: str | None
    status: str
    current_stage: str
    bot_paused: bool
    last_activity_at: datetime
    last_message_text: str | None
    last_message_direction: str | None
    has_pending_handoff: bool


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]
    next_cursor: str | None


# ---------- Cursor helpers ----------


def _encode_cursor(ts: datetime, conv_id: UUID) -> str:
    raw = json.dumps({"ts": ts.isoformat(), "id": str(conv_id)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        obj = json.loads(decoded)
        return datetime.fromisoformat(obj["ts"]), UUID(obj["id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from e


# ---------- Routes ----------


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user: AuthUser = Depends(current_user),  # noqa: ARG001 — RBAC enforced via dep
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    conv_status: str | None = Query(None, alias="status"),
    has_pending_handoff: bool = Query(False),
    bot_paused: bool | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationListResponse:
    # Subquery: last message per conversation (text + direction). Window
    # function avoids the N+1 of a per-row fetch.
    last_msg_sq = (
        select(
            MessageRow.conversation_id.label("cid"),
            MessageRow.text.label("text"),
            MessageRow.direction.label("direction"),
            func.row_number()
            .over(
                partition_by=MessageRow.conversation_id,
                order_by=MessageRow.created_at.desc(),
            )
            .label("rn"),
        )
        .where(MessageRow.tenant_id == tenant_id)
        .subquery()
    )
    last_msg = (
        select(last_msg_sq.c.cid, last_msg_sq.c.text, last_msg_sq.c.direction)
        .where(last_msg_sq.c.rn == 1)
        .subquery()
    )

    pending_handoff_exists = exists(
        select(1)
        .select_from(HumanHandoff)
        .where(
            HumanHandoff.conversation_id == Conversation.id,
            HumanHandoff.status == "open",
        )
    )

    stmt = (
        select(
            Conversation.id,
            Conversation.tenant_id,
            Conversation.customer_id,
            Conversation.status,
            Conversation.current_stage,
            Conversation.last_activity_at,
            Customer.phone_e164.label("customer_phone"),
            Customer.name.label("customer_name"),
            ConversationStateRow.bot_paused,
            last_msg.c.text.label("last_message_text"),
            last_msg.c.direction.label("last_message_direction"),
            pending_handoff_exists.label("has_pending_handoff"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(last_msg, last_msg.c.cid == Conversation.id)
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.last_activity_at.desc(), Conversation.id.desc())
        .limit(limit + 1)  # fetch one extra to know if there's more
    )

    if conv_status is not None:
        stmt = stmt.where(Conversation.status == conv_status)

    if bot_paused is not None:
        stmt = stmt.where(ConversationStateRow.bot_paused.is_(bot_paused))

    if has_pending_handoff:
        stmt = stmt.where(pending_handoff_exists)

    if cursor is not None:
        cur_ts, cur_id = _decode_cursor(cursor)
        # Strict less-than: skip the row identified by the cursor (it was
        # the last item of the previous page).
        stmt = stmt.where(
            or_(
                Conversation.last_activity_at < cur_ts,
                and_(
                    Conversation.last_activity_at == cur_ts,
                    Conversation.id < cur_id,
                ),
            )
        )

    rows = (await session.execute(stmt)).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        ConversationListItem(
            id=r.id,
            tenant_id=r.tenant_id,
            customer_id=r.customer_id,
            customer_phone=r.customer_phone,
            customer_name=r.customer_name,
            status=r.status,
            current_stage=r.current_stage,
            bot_paused=r.bot_paused,
            last_activity_at=r.last_activity_at,
            last_message_text=r.last_message_text,
            last_message_direction=r.last_message_direction,
            has_pending_handoff=r.has_pending_handoff,
        )
        for r in page
    ]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.last_activity_at, last.id)

    return ConversationListResponse(items=items, next_cursor=next_cursor)

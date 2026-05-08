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
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.config import get_settings
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.message import MessageRow
from atendia.db.session import get_db_session
from atendia.realtime.publisher import publish_event

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


class ConversationDetail(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    customer_phone: str
    customer_name: str | None
    status: str
    current_stage: str
    bot_paused: bool
    last_activity_at: datetime
    created_at: datetime
    extracted_data: dict
    pending_confirmation: str | None
    last_intent: str | None


class MessageItem(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: str
    text: str
    metadata: dict
    created_at: datetime
    sent_at: datetime | None


class MessageListResponse(BaseModel):
    items: list[MessageItem]
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


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationDetail:
    stmt = (
        select(
            Conversation.id,
            Conversation.tenant_id,
            Conversation.customer_id,
            Conversation.status,
            Conversation.current_stage,
            Conversation.last_activity_at,
            Conversation.created_at,
            Customer.phone_e164.label("customer_phone"),
            Customer.name.label("customer_name"),
            ConversationStateRow.bot_paused,
            ConversationStateRow.extracted_data,
            ConversationStateRow.pending_confirmation,
            ConversationStateRow.last_intent,
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return ConversationDetail(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        customer_phone=row.customer_phone,
        customer_name=row.customer_name,
        status=row.status,
        current_stage=row.current_stage,
        bot_paused=row.bot_paused,
        last_activity_at=row.last_activity_at,
        created_at=row.created_at,
        extracted_data=row.extracted_data or {},
        pending_confirmation=row.pending_confirmation,
        last_intent=row.last_intent,
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(
        None, description="Same cursor format as /conversations list"
    ),
    session: AsyncSession = Depends(get_db_session),
) -> MessageListResponse:
    """Returns messages newest-first (operator scrolls UP into history,
    same as WhatsApp). Tenant-scoped — 404 if the conversation isn't in
    this tenant, NOT 403, to avoid leaking conversation existence."""
    # Existence check first so we can 404 cleanly.
    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    # Order by `sent_at` (conversational time), NOT `created_at` (DB insert
    # time). For an operator scrolling history, "newest first" means
    # most-recently-sent — backfilled or replayed messages should land in
    # their conversational position, not at the top.
    stmt = (
        select(
            MessageRow.id,
            MessageRow.conversation_id,
            MessageRow.direction,
            MessageRow.text,
            MessageRow.metadata_json,
            MessageRow.created_at,
            MessageRow.sent_at,
        )
        .where(MessageRow.conversation_id == conversation_id)
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(limit + 1)
    )

    if cursor is not None:
        cur_ts, cur_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                MessageRow.sent_at < cur_ts,
                and_(MessageRow.sent_at == cur_ts, MessageRow.id < cur_id),
            )
        )

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        MessageItem(
            id=r.id,
            conversation_id=r.conversation_id,
            direction=r.direction,
            text=r.text,
            metadata=r.metadata_json or {},
            created_at=r.created_at,
            sent_at=r.sent_at,
        )
        for r in page
    ]
    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        # sent_at is NOT NULL for messages; reflected in the cursor too.
        assert last.sent_at is not None
        next_cursor = _encode_cursor(last.sent_at, last.id)
    return MessageListResponse(items=items, next_cursor=next_cursor)


# ---------- Operator intervention (Phase 4 T22-T23) ----------


class InterveneBody(BaseModel):
    text: str


class MessageSentResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    text: str
    sent_at: datetime


@router.post("/{conversation_id}/intervene", response_model=MessageSentResponse)
async def intervene(
    conversation_id: UUID,
    body: InterveneBody,
    request: Request,  # noqa: ARG001
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> MessageSentResponse:
    """Operator takes over the conversation.

    1. Sets `conversation_state.bot_paused = True`. The runner short-circuits
       on next inbound (T24).
    2. Inserts an outbound message row attributed to the operator
       (`metadata.source = "operator"`, `metadata.operator_user_id`).
    3. Publishes a `message_sent` event so the frontend list+detail
       refresh in real time.
    4. Best-effort: enqueues the actual WhatsApp send via arq if a pool
       is available. In tests / dev without arq the row is still
       persisted, but the customer won't physically receive it. The
       outbound dispatcher worker is a separate process; this route
       does NOT block on its delivery.
    """
    if not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text is required")

    # Existence check — also guards against operator → other tenant.
    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    now = datetime.now(UTC)

    # 1. Pause the bot.
    await session.execute(
        update(ConversationStateRow)
        .where(ConversationStateRow.conversation_id == conversation_id)
        .values(bot_paused=True)
    )

    # 2. Persist the outbound message attributed to the operator.
    msg_id = (
        await session.execute(
            MessageRow.__table__.insert()
            .values(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                direction="outbound",
                text=body.text,
                sent_at=now,
                metadata_json={
                    "source": "operator",
                    "operator_user_id": str(user.user_id),
                },
            )
            .returning(MessageRow.id)
        )
    ).scalar_one()

    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(last_activity_at=now)
    )
    await session.commit()

    # 3. Best-effort live notification.
    try:
        redis = Redis.from_url(get_settings().redis_url)
        try:
            await publish_event(
                redis,
                tenant_id=str(tenant_id),
                conversation_id=str(conversation_id),
                event={
                    "type": "message_sent",
                    "source": "operator",
                    "text": body.text,
                },
            )
        finally:
            await redis.aclose()
    except Exception:  # pragma: no cover
        pass

    # 4. Actual WhatsApp send is the outbound worker's job (Phase 2).
    # The route stays sync-fast; the worker reads its own queue.

    return MessageSentResponse(
        id=msg_id,
        conversation_id=conversation_id,
        text=body.text,
        sent_at=now,
    )


@router.post("/{conversation_id}/resume-bot")
async def resume_bot(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    """Flips bot_paused back to False. The next inbound goes through the
    normal runner pipeline."""
    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    await session.execute(
        update(ConversationStateRow)
        .where(ConversationStateRow.conversation_id == conversation_id)
        .values(bot_paused=False)
    )
    await session.commit()
    return {"ok": True}


# ---------- Partial update (scope gaps) ----------


class ConversationPatchResponse(BaseModel):
    id: UUID
    current_stage: str
    assigned_user_id: UUID | None
    assigned_user_email: str | None
    tags: list[str]
    unread_count: int
    status: str


@router.patch("/{conversation_id}", response_model=ConversationPatchResponse)
async def patch_conversation(
    conversation_id: UUID,
    body: Request,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationPatchResponse:
    """Partial update: change stage, assign/unassign user, set tags."""
    raw = await body.json()

    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    values: dict = {}
    if "current_stage" in raw and raw["current_stage"] is not None:
        values["current_stage"] = raw["current_stage"]
    if "assigned_user_id" in raw:
        values["assigned_user_id"] = raw["assigned_user_id"]  # None = unassign
    if "tags" in raw and raw["tags"] is not None:
        values["tags"] = raw["tags"]

    if values:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**values)
        )

    # Audit event
    from atendia.contracts.event import EventType
    from atendia.state_machine.event_emitter import EventEmitter
    emitter = EventEmitter(session)
    await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.CONVERSATION_UPDATED,
        payload={"fields": list(values.keys()), "by": str(user.user_id)},
    )

    await session.commit()

    # Re-fetch with joined user email
    from atendia.db.models.tenant import TenantUser
    row = (await session.execute(
        select(
            Conversation.id,
            Conversation.current_stage,
            Conversation.assigned_user_id,
            Conversation.tags,
            Conversation.unread_count,
            Conversation.status,
            TenantUser.email.label("assigned_user_email"),
        )
        .select_from(Conversation)
        .outerjoin(TenantUser, TenantUser.id == Conversation.assigned_user_id)
        .where(Conversation.id == conversation_id)
    )).first()

    return ConversationPatchResponse(
        id=row.id,
        current_stage=row.current_stage,
        assigned_user_id=row.assigned_user_id,
        assigned_user_email=row.assigned_user_email,
        tags=row.tags or [],
        unread_count=row.unread_count,
        status=row.status,
    )

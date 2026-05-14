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
import re
from datetime import UTC, datetime
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.channels.base import OutboundMessage
from atendia.config import get_settings
from atendia.db.models.conversation import Conversation, ConversationRead, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue
from atendia.db.models.customer_note import CustomerNote
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.message import MessageRow
from atendia.db.session import get_db_session
from atendia.queue.enqueue import enqueue_outbound
from atendia.queue.outbox import stage_outbound
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
    assigned_user_id: UUID | None = None
    assigned_user_email: str | None = None
    assigned_agent_id: UUID | None = None
    assigned_agent_name: str | None = None
    unread_count: int = 0
    tags: list[str] = []


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
    assigned_user_id: UUID | None = None
    assigned_user_email: str | None = None
    assigned_agent_id: UUID | None = None
    assigned_agent_name: str | None = None
    # Most recent INBOUND message timestamp. Used by the frontend to render
    # an outside-24h banner (loophole C-2): outside this window, free-form
    # outbound is blocked by WhatsApp until templates ship (Phase 3d.2).
    last_inbound_at: datetime | None = None
    unread_count: int = 0
    tags: list[str] = []
    customer_fields: list[CustomerFieldInfo] = []
    customer_notes: list[CustomerNoteInfo] = []
    required_docs: list[RequiredDocInfo] = []


class CustomerFieldInfo(BaseModel):
    key: str
    label: str
    field_type: str
    value: str | None


class CustomerNoteInfo(BaseModel):
    id: UUID
    author_email: str | None
    content: str
    source: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


class RequiredDocInfo(BaseModel):
    field_name: str
    label: str
    present: bool


class MessageItem(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: str
    text: str
    metadata: dict
    created_at: datetime
    sent_at: datetime | None
    delivery_status: str | None = None


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


async def _active_pipeline_stage_ids(
    session: AsyncSession, tenant_id: UUID
) -> set[str] | None:
    from atendia.db.models.tenant_config import TenantPipeline

    definition = (
        await session.execute(
            select(TenantPipeline.definition)
            .where(
                TenantPipeline.tenant_id == tenant_id,
                TenantPipeline.active.is_(True),
            )
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if definition is None:
        return None
    stages = definition.get("stages") if isinstance(definition, dict) else None
    if not isinstance(stages, list):
        return set()
    return {
        stage["id"]
        for stage in stages
        if isinstance(stage, dict) and isinstance(stage.get("id"), str)
    }


def _user_unread_count_expr(*, tenant_id: UUID, user_id: UUID):
    msg = aliased(MessageRow)
    last_read_at = (
        select(ConversationRead.last_read_at)
        .where(
            ConversationRead.conversation_id == Conversation.id,
            ConversationRead.user_id == user_id,
        )
        .correlate(Conversation)
        .scalar_subquery()
    )
    return (
        select(func.count(msg.id))
        .where(
            msg.tenant_id == tenant_id,
            msg.conversation_id == Conversation.id,
            msg.direction == "inbound",
            msg.sent_at > func.coalesce(
                last_read_at, datetime(1970, 1, 1, tzinfo=UTC)
            ),
        )
        .correlate(Conversation)
        .scalar_subquery()
    )


async def _customer_fields(
    session: AsyncSession, tenant_id: UUID, customer_id: UUID
) -> list[CustomerFieldInfo]:
    rows = (
        await session.execute(
            select(
                CustomerFieldDefinition.key,
                CustomerFieldDefinition.label,
                CustomerFieldDefinition.field_type,
                CustomerFieldValue.value,
            )
            .select_from(CustomerFieldDefinition)
            .outerjoin(
                CustomerFieldValue,
                and_(
                    CustomerFieldValue.field_definition_id == CustomerFieldDefinition.id,
                    CustomerFieldValue.customer_id == customer_id,
                ),
            )
            .where(CustomerFieldDefinition.tenant_id == tenant_id)
            .order_by(CustomerFieldDefinition.ordering.asc(), CustomerFieldDefinition.created_at.asc())
        )
    ).all()
    return [
        CustomerFieldInfo(
            key=row.key,
            label=row.label,
            field_type=row.field_type,
            value=row.value,
        )
        for row in rows
    ]


async def _customer_notes(
    session: AsyncSession, tenant_id: UUID, customer_id: UUID
) -> list[CustomerNoteInfo]:
    from atendia.db.models.tenant import TenantUser

    rows = (
        await session.execute(
            select(
                CustomerNote.id,
                TenantUser.email.label("author_email"),
                CustomerNote.content,
                CustomerNote.source,
                CustomerNote.pinned,
                CustomerNote.created_at,
                CustomerNote.updated_at,
            )
            .select_from(CustomerNote)
            .outerjoin(TenantUser, TenantUser.id == CustomerNote.author_user_id)
            .where(CustomerNote.tenant_id == tenant_id, CustomerNote.customer_id == customer_id)
            .order_by(CustomerNote.pinned.desc(), CustomerNote.created_at.desc())
            .limit(5)
        )
    ).all()
    return [CustomerNoteInfo(**row._mapping) for row in rows]


_DOC_STATUS_RE = re.compile(r"^(DOCS_[A-Z_]+)\.status$")


async def _required_docs(
    session: AsyncSession,
    tenant_id: UUID,
    extracted_data: dict,
    customer_attrs: dict | None = None,
) -> list[RequiredDocInfo]:
    """Required-docs checklist surfaced on the contact panel.

    Source of truth (in priority order):

    1. **Pipeline `auto_enter_rules.conditions`** — every stage whose
       rules require ``DOCS_<KEY>.status equals "ok"`` declares
       ``<KEY>`` as a required document. This is exactly what the
       Pipeline editor's "Documentos requeridos" checklist writes
       (`DocumentRuleBuilder.tsx`), so what the operator checks there
       lights up automatically here. Aggregated across *all* stages so
       a contact can see the full set of docs they'll eventually need,
       not just the docs for their current stage.

    2. **Legacy `docs_per_plan`** — older tenants populated a
       plan-keyed dict directly in the pipeline JSON. Honored as a
       fallback when no auto-enter rule mentions documents, so we
       don't regress those tenants.

    Presence (`present=True`) is resolved against the customer's
    `attrs` first (where uploaded-doc statuses live) and falls back to
    the conversation's `extracted_data` for plan-keyed legacy values.
    """
    from atendia.contracts.documents_catalog import humanize_doc_key
    from atendia.db.models.tenant_config import TenantPipeline
    from atendia.state_machine.pipeline_evaluator import resolve_field_path

    definition = (
        await session.execute(
            select(TenantPipeline.definition)
            .where(TenantPipeline.tenant_id == tenant_id, TenantPipeline.active.is_(True))
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not isinstance(definition, dict):
        return []

    # ── 1. Aggregate DOCS_*.status from every stage's rules ─────────
    seen: dict[str, str] = {}  # field_path -> friendly label
    for stage in definition.get("stages", []) or []:
        if not isinstance(stage, dict):
            continue
        rules = stage.get("auto_enter_rules")
        if not isinstance(rules, dict):
            continue
        for cond in rules.get("conditions") or []:
            if not isinstance(cond, dict):
                continue
            field = cond.get("field")
            if not isinstance(field, str):
                continue
            m = _DOC_STATUS_RE.match(field)
            if not m:
                continue
            seen.setdefault(field, humanize_doc_key(m.group(1)))

    if seen:
        items: list[RequiredDocInfo] = []
        for field_path, label in seen.items():
            # Resolve against customer.attrs first (canonical for
            # uploaded-doc statuses), then conversation extracted_data.
            value = None
            if customer_attrs:
                value = resolve_field_path(customer_attrs, field_path)
            if value is None:
                value = resolve_field_path(extracted_data, field_path)
            # "Present" = the resolved status is "ok"; any other value
            # (None, "missing", "pending") still counts as not-yet-done.
            present = isinstance(value, str) and value.lower() == "ok"
            items.append(
                RequiredDocInfo(field_name=field_path, label=label, present=present)
            )
        return items

    # ── 2. Legacy fallback: docs_per_plan ──────────────────────────
    docs_per_plan = definition.get("docs_per_plan")
    if not isinstance(docs_per_plan, dict):
        return []
    plan_raw = extracted_data.get("plan_credito")
    plan = plan_raw.get("value") if isinstance(plan_raw, dict) else plan_raw
    required = docs_per_plan.get(str(plan)) or docs_per_plan.get("default") or []
    if not isinstance(required, list):
        return []
    items = []
    for item in required:
        if isinstance(item, str):
            field_name = item
            label = item.replace("_", " ")
        elif isinstance(item, dict) and isinstance(item.get("field_name") or item.get("field"), str):
            field_name = item.get("field_name") or item.get("field")
            label = item.get("label") or field_name.replace("_", " ")
        else:
            continue
        raw = extracted_data.get(field_name)
        value = raw.get("value") if isinstance(raw, dict) else raw
        items.append(RequiredDocInfo(field_name=field_name, label=label, present=bool(value)))
    return items


# ---------- Routes ----------


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    conv_status: str | None = Query(None, alias="status"),
    has_pending_handoff: bool = Query(False),
    bot_paused: bool | None = Query(None),
    assigned_user_id: UUID | None = Query(None, alias="assigned_user_id"),
    unassigned: bool = Query(False),
    tag: str | None = Query(None),
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

    unread_count = _user_unread_count_expr(tenant_id=tenant_id, user_id=user.user_id)
    from atendia.db.models.agent import Agent as _AgentList
    from atendia.db.models.tenant import TenantUser as _TUList
    stmt = (
        select(
            Conversation.id,
            Conversation.tenant_id,
            Conversation.customer_id,
            Conversation.status,
            Conversation.current_stage,
            Conversation.last_activity_at,
            Conversation.assigned_user_id,
            Conversation.assigned_agent_id,
            unread_count.label("unread_count"),
            Conversation.tags,
            Customer.phone_e164.label("customer_phone"),
            Customer.name.label("customer_name"),
            ConversationStateRow.bot_paused,
            last_msg.c.text.label("last_message_text"),
            last_msg.c.direction.label("last_message_direction"),
            pending_handoff_exists.label("has_pending_handoff"),
            _TUList.email.label("assigned_user_email"),
            _AgentList.name.label("assigned_agent_name"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(last_msg, last_msg.c.cid == Conversation.id)
        .outerjoin(_TUList, _TUList.id == Conversation.assigned_user_id)
        .outerjoin(_AgentList, _AgentList.id == Conversation.assigned_agent_id)
        .where(Conversation.tenant_id == tenant_id)
        .where(Conversation.deleted_at.is_(None))
        .order_by(Conversation.last_activity_at.desc(), Conversation.id.desc())
        .limit(limit + 1)  # fetch one extra to know if there's more
    )

    if conv_status is not None:
        stmt = stmt.where(Conversation.status == conv_status)

    if bot_paused is not None:
        stmt = stmt.where(ConversationStateRow.bot_paused.is_(bot_paused))

    if has_pending_handoff:
        stmt = stmt.where(pending_handoff_exists)

    if assigned_user_id is not None:
        stmt = stmt.where(Conversation.assigned_user_id == assigned_user_id)

    if unassigned:
        stmt = stmt.where(Conversation.assigned_user_id.is_(None))

    if tag is not None:
        stmt = stmt.where(Conversation.tags.contains([tag]))

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
            assigned_user_id=r.assigned_user_id,
            assigned_user_email=r.assigned_user_email,
            assigned_agent_id=r.assigned_agent_id,
            assigned_agent_name=r.assigned_agent_name,
            unread_count=r.unread_count,
            tags=r.tags or [],
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
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationDetail:
    unread_count = _user_unread_count_expr(tenant_id=tenant_id, user_id=user.user_id)
    from atendia.db.models.agent import Agent as _AgentDetail
    from atendia.db.models.tenant import TenantUser as _TU
    last_inbound_sq = (
        select(
            func.max(MessageRow.sent_at).label("last_inbound_at"),
        )
        .where(
            MessageRow.conversation_id == conversation_id,
            MessageRow.direction == "inbound",
        )
        .scalar_subquery()
    )
    stmt = (
        select(
            Conversation.id,
            Conversation.tenant_id,
            Conversation.customer_id,
            Conversation.status,
            Conversation.current_stage,
            Conversation.last_activity_at,
            Conversation.created_at,
            Conversation.assigned_user_id,
            Conversation.assigned_agent_id,
            unread_count.label("unread_count"),
            Conversation.tags,
            Customer.phone_e164.label("customer_phone"),
            Customer.name.label("customer_name"),
            ConversationStateRow.bot_paused,
            ConversationStateRow.extracted_data,
            ConversationStateRow.pending_confirmation,
            ConversationStateRow.last_intent,
            _TU.email.label("assigned_user_email"),
            _AgentDetail.name.label("assigned_agent_name"),
            last_inbound_sq.label("last_inbound_at"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(_TU, _TU.id == Conversation.assigned_user_id)
        .outerjoin(_AgentDetail, _AgentDetail.id == Conversation.assigned_agent_id)
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.deleted_at.is_(None),
        )
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    # Pull the customer's `attrs` so `_required_docs` can resolve doc
    # statuses written by the upload/extraction sprint
    # (e.g. customer.attrs["DOCS_INE"]["status"] = "ok").
    customer_attrs = (
        await session.execute(
            select(Customer.attrs).where(Customer.id == row.customer_id)
        )
    ).scalar_one_or_none() or {}
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
        assigned_user_id=row.assigned_user_id,
        assigned_user_email=row.assigned_user_email,
        assigned_agent_id=row.assigned_agent_id,
        assigned_agent_name=row.assigned_agent_name,
        last_inbound_at=row.last_inbound_at,
        unread_count=row.unread_count,
        tags=row.tags or [],
        customer_fields=await _customer_fields(session, tenant_id, row.customer_id),
        customer_notes=await _customer_notes(session, tenant_id, row.customer_id),
        required_docs=await _required_docs(
            session,
            tenant_id,
            row.extracted_data or {},
            customer_attrs=customer_attrs if isinstance(customer_attrs, dict) else {},
        ),
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
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
            MessageRow.delivery_status,
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
            delivery_status=r.delivery_status,
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


class ProcessingResponse(BaseModel):
    status: str


@router.post("/{conversation_id}/intervene", response_model=MessageSentResponse)
async def intervene(
    conversation_id: UUID,
    body: InterveneBody,
    request: Request,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> MessageSentResponse:
    """Operator takes over the conversation.

    1. Sets `conversation_state.bot_paused = True`. The runner short-circuits
       on next inbound (T24).
    2. Stages an outbox row (deterministic UUID) and persists the outbound
       message row with that same UUID + `delivery_status='queued'`. The
       worker later UPDATEs the row via `ON CONFLICT (id)` with the real
       channel_message_id and delivery_status.
    3. Best-effort: enqueues `send_outbound` on arq so the worker actually
       hands the message to Meta / Baileys. Failure to enqueue does NOT
       fail the route — the cron `dispatch_outbox` will pick up the
       pending outbox row on its next tick.
    4. Publishes a `message_sent` event so the frontend list+detail
       refresh in real time.
    """
    if not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text is required")

    # Existence check — also guards against operator → other tenant.
    # Also fetch the customer's phone so we can address the WhatsApp send.
    row = (
        await session.execute(
            select(Conversation.id, Customer.phone_e164)
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    to_phone_e164 = row.phone_e164

    now = datetime.now(UTC)

    # 1. Pause the bot.
    await session.execute(
        update(ConversationStateRow)
        .where(ConversationStateRow.conversation_id == conversation_id)
        .values(bot_paused=True)
    )

    # 2. Stage the outbox row + persist the outbound message under the same UUID.
    #    Using the outbox.id as the message.id lets the worker's
    #    `INSERT ... ON CONFLICT (id) DO UPDATE` hit our pre-inserted row
    #    instead of creating a duplicate.
    idempotency_key = (
        f"intervene:{conversation_id}:{int(now.timestamp() * 1000)}"
    )
    outbound_msg = OutboundMessage(
        tenant_id=str(tenant_id),
        to_phone_e164=to_phone_e164,
        text=body.text,
        idempotency_key=idempotency_key,
        metadata={
            "source": "operator",
            "operator_user_id": str(user.user_id),
            "conversation_id": str(conversation_id),
        },
    )
    msg_id = await stage_outbound(session, outbound_msg)

    await session.execute(
        MessageRow.__table__.insert().values(
            id=msg_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            text=body.text,
            sent_at=now,
            delivery_status="queued",
            metadata_json={
                "source": "operator",
                "operator_user_id": str(user.user_id),
            },
        )
    )

    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(last_activity_at=now)
    )
    await session.commit()

    # 3. Enqueue the actual WhatsApp send. Best-effort: if the arq pool is
    #    unreachable the outbox row stays `pending` and the
    #    `dispatch_outbox` cron picks it up within ~5s.
    try:
        arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await enqueue_outbound(arq_pool, outbound_msg)
        finally:
            await arq_pool.aclose()
    except Exception:  # pragma: no cover - worker unavailable, cron will retry
        pass

    # 4. Best-effort live notification.
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

    return MessageSentResponse(
        id=msg_id,
        conversation_id=conversation_id,
        text=body.text,
        sent_at=now,
    )


@router.post("/{conversation_id}/resume-bot")
async def resume_bot(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
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


FORCE_SUMMARY_RATE_LIMIT_WINDOW_SECONDS: int = 60
FORCE_SUMMARY_RATE_LIMIT_MAX_CALLS: int = 30


async def _check_force_summary_rate_limit(tenant_id: UUID) -> None:
    """Per-tenant token bucket via Redis ``INCR`` + ``EXPIRE``. Raises 429
    when a tenant exceeds 30 force-summary calls per minute. Cost guard
    on top of the in-flight ``_job_id`` and ``high_water`` idempotency that
    already make duplicate calls cheap; this stops a runaway loop."""
    import redis.asyncio as redis_async

    client = redis_async.Redis.from_url(get_settings().redis_url)
    try:
        key = f"convs:force_summary_rl:{tenant_id}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, FORCE_SUMMARY_RATE_LIMIT_WINDOW_SECONDS)
        if count > FORCE_SUMMARY_RATE_LIMIT_MAX_CALLS:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"force-summary rate limit exceeded ({FORCE_SUMMARY_RATE_LIMIT_MAX_CALLS}/min)",
            )
    finally:
        await client.aclose()


@router.post("/{conversation_id}/force-summary", response_model=ProcessingResponse, status_code=status.HTTP_202_ACCEPTED)
async def force_summary_endpoint(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ProcessingResponse:
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
    await _check_force_summary_rate_limit(tenant_id)
    try:
        redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await redis.enqueue_job(
                "force_summary",
                str(conversation_id),
                _job_id=f"force_summary:{conversation_id}",
            )
        finally:
            await redis.aclose()
    except Exception:
        return ProcessingResponse(status="worker_unavailable")
    return ProcessingResponse(status="processing")


# ---------- Partial update (scope gaps) ----------


class ConversationPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_stage: str | None = Field(
        default=None, min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$"
    )
    assigned_user_id: UUID | None = None
    assigned_agent_id: UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=10)

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            tag = raw.strip().lower()
            if not tag:
                raise ValueError("tags cannot be blank")
            if len(tag) > 40:
                raise ValueError("tags cannot exceed 40 characters")
            if tag not in seen:
                seen.add(tag)
                normalized.append(tag)
        return normalized


class ConversationPatchResponse(BaseModel):
    id: UUID
    current_stage: str
    assigned_user_id: UUID | None
    assigned_user_email: str | None
    assigned_agent_id: UUID | None
    tags: list[str]
    unread_count: int
    status: str


@router.patch("/{conversation_id}", response_model=ConversationPatchResponse)
async def patch_conversation(
    conversation_id: UUID,
    body: ConversationPatchBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationPatchResponse:
    """Partial update: change stage, assign/unassign user, set tags."""
    own = (
        await session.execute(
            select(Conversation.id, Conversation.current_stage).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).first()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    values: dict = {}
    update_stage_entered_at = False
    fields = body.model_fields_set

    if "current_stage" in fields and body.current_stage is not None:
        stage_ids = await _active_pipeline_stage_ids(session, tenant_id)
        if stage_ids is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "tenant has no active pipeline"
            )
        if body.current_stage not in stage_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown pipeline stage")
        values["current_stage"] = body.current_stage
        update_stage_entered_at = body.current_stage != own.current_stage

    if "assigned_user_id" in fields:
        if body.assigned_user_id is not None:
            from atendia.db.models.tenant import TenantUser

            assignee = (
                await session.execute(
                    select(TenantUser.id).where(
                        TenantUser.id == body.assigned_user_id,
                        TenantUser.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if assignee is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "assigned user not found")
        values["assigned_user_id"] = body.assigned_user_id

    if "assigned_agent_id" in fields:
        if body.assigned_agent_id is not None:
            from atendia.db.models.agent import Agent

            agent = (
                await session.execute(
                    select(Agent.id).where(
                        Agent.id == body.assigned_agent_id,
                        Agent.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if agent is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "assigned agent not found")
        values["assigned_agent_id"] = body.assigned_agent_id

    if "tags" in fields and body.tags is not None:
        values["tags"] = body.tags

    if values:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**values)
        )
        if update_stage_entered_at:
            await session.execute(
                update(ConversationStateRow)
                .where(ConversationStateRow.conversation_id == conversation_id)
                .values(stage_entered_at=datetime.now(UTC))
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

        # Realtime fan-out so the operator's other tabs/sessions see the
        # change without a manual reload (closes loophole C-3 from the
        # conversations runbook). Best-effort — failure here doesn't undo
        # the persisted patch.
        try:
            import redis.asyncio as redis_async
            redis_client = redis_async.Redis.from_url(get_settings().redis_url)
            try:
                await publish_event(
                    redis_client,
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                    event={
                        "type": "conversation_updated",
                        "data": {
                            "conversation_id": str(conversation_id),
                            "fields": sorted(values.keys()),
                        },
                    },
                )
            finally:
                await redis_client.aclose()
        except Exception:
            pass

    # Re-fetch with joined user email
    from atendia.db.models.tenant import TenantUser
    unread_count = _user_unread_count_expr(tenant_id=tenant_id, user_id=user.user_id)
    row = (await session.execute(
        select(
            Conversation.id,
            Conversation.current_stage,
            Conversation.assigned_user_id,
            Conversation.assigned_agent_id,
            Conversation.tags,
            unread_count.label("unread_count"),
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
        assigned_agent_id=row.assigned_agent_id,
        tags=row.tags or [],
        unread_count=row.unread_count,
        status=row.status,
    )


# ---------- Soft delete ----------


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete: sets deleted_at, excluded from list/detail."""
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

    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(deleted_at=datetime.now(UTC))
    )

    from atendia.contracts.event import EventType
    from atendia.state_machine.event_emitter import EventEmitter
    emitter = EventEmitter(session)
    await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.CONVERSATION_DELETED,
        payload={"by": str(user.user_id)},
    )
    await session.commit()


# ---------- Mark read ----------


@router.post("/{conversation_id}/mark-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Reset unread_count to 0 — called when operator opens a conversation."""
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

    latest = (
        await session.execute(
            select(MessageRow.id, MessageRow.sent_at)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.tenant_id == tenant_id,
                MessageRow.direction == "inbound",
            )
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        )
    ).first()
    last_read_at = latest.sent_at if latest and latest.sent_at else datetime.now(UTC)
    last_read_message_id = latest.id if latest else None

    await session.execute(
        text(
            """
            INSERT INTO conversation_reads
                (tenant_id, conversation_id, user_id, last_read_at, last_read_message_id)
            VALUES (:tenant_id, :conversation_id, :user_id, :last_read_at, :message_id)
            ON CONFLICT (conversation_id, user_id) DO UPDATE SET
                last_read_at = EXCLUDED.last_read_at,
                last_read_message_id = EXCLUDED.last_read_message_id,
                updated_at = NOW()
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "user_id": user.user_id,
            "last_read_at": last_read_at,
            "message_id": last_read_message_id,
        },
    )
    # Keep the legacy aggregate column harmless for old callers; API responses
    # now compute unread per user from conversation_reads + messages.
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(unread_count=0)
    )
    await session.commit()

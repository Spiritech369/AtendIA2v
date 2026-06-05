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
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from atendia.agent_runtime import (
    AgentRuntime,
    AgentRuntimeV2PilotPolicyService,
    ContextBuilder,
    PolicyValidationError,
    PolicyValidator,
    PostTurnActionExecutor,
    RolloutDecision,
    RolloutPolicyService,
    TurnContext,
    TurnInput,
    TurnOutput,
)
from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.model_provider import build_agent_turn_provider
from atendia.agent_runtime.pilot_policy import PilotDecision
from atendia.agent_runtime.workflow_events import AgentWorkflowEventEmitter
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.api.message_attachments import list_attachments_for_messages
from atendia.channels.base import OutboundMessage
from atendia.config import get_settings
from atendia.db.models.conversation import Conversation, ConversationRead, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue
from atendia.db.models.customer_note import CustomerNote
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.models.message import MessageRow
from atendia.db.models.turn_trace import TurnTrace
from atendia.db.session import get_db_session
from atendia.knowledge.os import UnifiedKnowledgeProvider
from atendia.queue.enqueue import enqueue_outbound
from atendia.queue.outbox import stage_outbound
from atendia.realtime.publisher import publish_event
from atendia.runner.conversation_events import emit_stage_changed

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
    group: str = "datos_comerciales"
    render_mode: str = "text"
    render_payload: Any | None = None
    display_order: int = 1000
    is_debug: bool = False


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
    # C9 — set when an operator edits the text; frontend shows "editado".
    edited_at: datetime | None = None


class MessageListResponse(BaseModel):
    items: list[MessageItem]
    next_cursor: str | None


class ConversationAttachmentItem(BaseModel):
    id: UUID
    message_id: UUID
    type: str
    mime_type: str
    url: str
    caption: str | None = None
    original_filename: str | None = None
    file_size: int | None = None
    status: str
    sent_at: datetime | None = None
    created_at: datetime


def _message_metadata_with_attachments(metadata: dict, attachments: list[dict]) -> dict:
    if not attachments:
        return metadata
    merged = dict(metadata or {})
    merged["attachments"] = attachments
    if "media" not in merged:
        merged["media"] = attachments[0]
    return merged


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


async def _active_pipeline_stage_ids(session: AsyncSession, tenant_id: UUID) -> set[str] | None:
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
            msg.sent_at > func.coalesce(last_read_at, datetime(1970, 1, 1, tzinfo=UTC)),
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
            .order_by(
                CustomerFieldDefinition.ordering.asc(), CustomerFieldDefinition.created_at.asc()
            )
        )
    ).all()
    return [
        CustomerFieldInfo(
            key=row.key,
            label=row.label,
            field_type=row.field_type,
            value=row.value,
            **_customer_field_presentation(row.key, row.value),
        )
        for row in rows
    ]


def _customer_field_presentation(key: str, value: str | None) -> dict[str, Any]:
    display_order_by_key = {
        "Cumple_Antiguedad": 10,
        "Plan_Credito": 20,
        "Plan_Enganche": 30,
        "Moto": 40,
        "Doc_Incompletos": 50,
        "Doc_Completos": 60,
        "Autorizado": 70,
        "Cotizacion_Enviada": 110,
        "Ultima_Cotizacion": 120,
        "Docs_Checklist": 130,
        "Handoff_Humano": 140,
        "is_simulation": 210,
        "simulation_run_id": 220,
        "simulation_case_id": 230,
        "initial_fields": 240,
    }
    commercial = {
        "Cumple_Antiguedad",
        "Plan_Credito",
        "Plan_Enganche",
        "Moto",
        "Doc_Incompletos",
        "Doc_Completos",
        "Autorizado",
    }
    technical = {"Cotizacion_Enviada", "Ultima_Cotizacion", "Docs_Checklist", "Handoff_Humano"}
    debug = {"is_simulation", "simulation_run_id", "simulation_case_id", "initial_fields"}
    if key in technical:
        group = "tecnicos"
    elif key in debug:
        group = "debug"
    elif key in commercial:
        group = "datos_comerciales"
    else:
        group = "datos_comerciales"

    checkbox_keys = {
        "Cumple_Antiguedad",
        "Doc_Completos",
        "Autorizado",
        "Cotizacion_Enviada",
        "Handoff_Humano",
    }
    render_mode = "checkbox" if key in checkbox_keys else "text"
    payload = _json_value(value)
    if key == "Ultima_Cotizacion":
        render_mode = "quote_card"
    elif key == "Docs_Checklist":
        render_mode = "document_checklist"
    return {
        "group": group,
        "render_mode": render_mode,
        "render_payload": payload,
        "display_order": display_order_by_key.get(key, 1000),
        "is_debug": key in debug,
    }


def _json_value(value: str | None) -> Any | None:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


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

    # Tenant-configured catalog wins for label resolution. The hardcoded
    # `humanize_doc_key` only fires as a last-resort fallback when a
    # rule references a DOCS_* key that the operator removed from the
    # catalog (orphan), so the contact panel still shows something
    # readable instead of the raw identifier.
    tenant_catalog: dict[str, str] = {}
    for d in definition.get("documents_catalog") or []:
        if isinstance(d, dict):
            k = d.get("key")
            lbl = d.get("label")
            if isinstance(k, str) and isinstance(lbl, str) and lbl:
                tenant_catalog[k] = lbl

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
            doc_key = m.group(1)
            label = tenant_catalog.get(doc_key) or humanize_doc_key(doc_key)
            seen.setdefault(field, label)

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
            items.append(RequiredDocInfo(field_name=field_path, label=label, present=present))
        return items

    # ── 2. Legacy fallback: docs_per_plan ──────────────────────────
    docs_per_plan = definition.get("docs_per_plan")
    if not isinstance(docs_per_plan, dict):
        return []
    plan_fields = [
        definition.get("docs_plan_field"),
        "plan_credito",
        "credito_plan",
        "tipo_credito",
    ]
    plan = None
    for field in plan_fields:
        if not isinstance(field, str) or not field:
            continue
        raw = None
        if customer_attrs:
            raw = resolve_field_path(customer_attrs, field)
        if raw is None:
            raw = resolve_field_path(extracted_data, field)
        if isinstance(raw, dict):
            raw = raw.get("value")
        if raw not in (None, ""):
            plan = raw
            break
    required = docs_per_plan.get(str(plan)) or docs_per_plan.get("default") or []
    if not isinstance(required, list):
        return []
    items = []
    for item in required:
        if isinstance(item, str):
            field_name = item
            label = item.replace("_", " ")
        elif isinstance(item, dict) and isinstance(
            item.get("field_name") or item.get("field"), str
        ):
            field_name = item.get("field_name") or item.get("field")
            label = item.get("label") or field_name.replace("_", " ")
        else:
            continue
        doc_key = field_name.split(".", 1)[0]
        field_path = field_name if "." in field_name else f"{doc_key}.status"
        value = None
        if customer_attrs:
            value = resolve_field_path(customer_attrs, field_path)
            if value is None:
                value = resolve_field_path(customer_attrs, doc_key)
        if value is None:
            value = resolve_field_path(extracted_data, field_path)
            if value is None:
                value = resolve_field_path(extracted_data, doc_key)
        if isinstance(value, dict):
            value = value.get("status") or value.get("value")
        present = isinstance(value, str) and value.lower() == "ok"
        if isinstance(value, bool):
            present = value
        items.append(
            RequiredDocInfo(
                field_name=field_path,
                label=tenant_catalog.get(doc_key) or label,
                present=present,
            )
        )
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
    from atendia.db.models.agent import Agent as AgentListRow
    from atendia.db.models.tenant import TenantUser as TenantUserListRow

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
            TenantUserListRow.email.label("assigned_user_email"),
            AgentListRow.name.label("assigned_agent_name"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(last_msg, last_msg.c.cid == Conversation.id)
        .outerjoin(TenantUserListRow, TenantUserListRow.id == Conversation.assigned_user_id)
        .outerjoin(AgentListRow, AgentListRow.id == Conversation.assigned_agent_id)
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
    from atendia.db.models.agent import Agent as AgentDetailRow
    from atendia.db.models.tenant import TenantUser as TenantUserDetailRow

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
            TenantUserDetailRow.email.label("assigned_user_email"),
            AgentDetailRow.name.label("assigned_agent_name"),
            last_inbound_sq.label("last_inbound_at"),
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .outerjoin(TenantUserDetailRow, TenantUserDetailRow.id == Conversation.assigned_user_id)
        .outerjoin(AgentDetailRow, AgentDetailRow.id == Conversation.assigned_agent_id)
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
        await session.execute(select(Customer.attrs).where(Customer.id == row.customer_id))
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


@router.get("/{conversation_id}/attachments", response_model=list[ConversationAttachmentItem])
async def list_conversation_attachments(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConversationAttachmentItem]:
    """Files sent by the customer in this conversation, newest first."""
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

    rows = (
        await session.execute(
            text(
                """
                SELECT a.id, a.message_id, a.type, a.mime_type,
                       a.storage_url AS url, a.caption, a.original_filename,
                       a.file_size, a.status, m.sent_at, a.created_at
                FROM message_attachments a
                JOIN messages m ON m.id = a.message_id
                WHERE a.tenant_id = :tenant_id
                  AND m.conversation_id = :conversation_id
                  AND m.direction = 'inbound'
                  AND m.deleted_at IS NULL
                ORDER BY COALESCE(m.sent_at, a.created_at) DESC, a.created_at DESC, a.id DESC
                LIMIT 100
                """
            ),
            {"tenant_id": tenant_id, "conversation_id": conversation_id},
        )
    ).mappings()
    return [ConversationAttachmentItem(**row) for row in rows]


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None, description="Same cursor format as /conversations list"),
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
            MessageRow.edited_at,
        )
        .where(
            MessageRow.conversation_id == conversation_id,
            # C9 — soft-deleted messages are kept for audit but hidden.
            MessageRow.deleted_at.is_(None),
        )
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
    attachments_by_message = await list_attachments_for_messages(
        session,
        message_ids=[r.id for r in page],
    )

    items = [
        MessageItem(
            id=r.id,
            conversation_id=r.conversation_id,
            direction=r.direction,
            text=r.text,
            metadata=_message_metadata_with_attachments(
                r.metadata_json or {},
                attachments_by_message.get(r.id) or [],
            ),
            created_at=r.created_at,
            sent_at=r.sent_at,
            delivery_status=r.delivery_status,
            edited_at=r.edited_at,
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


# ---------- C9: per-message edit / soft delete ----------


class EditMessageBody(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text must not be empty")
        return v.strip()


async def _own_message_or_404(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    message_id: UUID,
    tenant_id: UUID,
) -> MessageRow:
    row = (
        await session.execute(
            select(MessageRow).where(
                MessageRow.id == message_id,
                MessageRow.conversation_id == conversation_id,
                MessageRow.tenant_id == tenant_id,
                MessageRow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    return row


@router.patch("/{conversation_id}/messages/{message_id}", response_model=MessageItem)
async def edit_message(
    conversation_id: UUID,
    message_id: UUID,
    body: EditMessageBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> MessageItem:
    """Edit a message's text in place (e.g. redact PII, fix a typo in
    an operator reply). Stamps ``edited_at`` so the UI can flag it.
    Tenant-scoped; 404 if the message isn't in this conversation."""
    msg = await _own_message_or_404(
        session,
        conversation_id=conversation_id,
        message_id=message_id,
        tenant_id=tenant_id,
    )
    msg.text = body.text
    msg.edited_at = datetime.now(UTC)
    session.add(msg)
    await session.commit()
    return MessageItem(
        id=msg.id,
        conversation_id=msg.conversation_id,
        direction=msg.direction,
        text=msg.text,
        metadata=msg.metadata_json or {},
        created_at=msg.created_at,
        sent_at=msg.sent_at,
        delivery_status=msg.delivery_status,
        edited_at=msg.edited_at,
    )


@router.delete("/{conversation_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete a message: the row is kept for audit/forensics but
    the list endpoint filters it out. Idempotent — re-deleting an
    already-deleted message just 404s (it's no longer visible)."""
    msg = await _own_message_or_404(
        session,
        conversation_id=conversation_id,
        message_id=message_id,
        tenant_id=tenant_id,
    )
    msg.deleted_at = datetime.now(UTC)
    session.add(msg)
    await session.commit()


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


class AgentRuntimeV2ConversationResponse(BaseModel):
    final_message: str
    knowledge_citations: list[dict]
    field_updates: list[dict]
    lifecycle_update: dict | None
    actions: list[dict]
    confidence: float
    needs_human: bool
    risk_flags: list[str]
    trace_metadata: dict
    debug: dict


class AgentRuntimeV2SendResponse(AgentRuntimeV2ConversationResponse):
    message_id: UUID | None = None
    outbox_id: UUID | None = None


def _agent_runtime_v2_settings_or_403() -> object:
    settings = get_settings()
    if not settings.agent_runtime_v2_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "agent_runtime_v2 is disabled")
    return settings


def _build_conversation_agent_runtime(context: TurnContext) -> AgentRuntime:
    return AgentRuntime(
        context_builder=_StaticContextBuilder(context),
        provider=build_agent_turn_provider(
            model_provider_allowed=_model_provider_allowed_from_context(context),
        ),
    )


def _model_provider_allowed_from_context(context: TurnContext) -> bool | None:
    rollout = context.metadata.get("rollout")
    if not isinstance(rollout, dict):
        return None
    value = rollout.get("model_provider_allowed")
    return value if isinstance(value, bool) else None


def _rollout_http_error(decision: RolloutDecision) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        {
            "message": f"agent_runtime_v2 {decision.capability} is not allowed",
            "rollout": decision.model_dump(mode="json"),
        },
    )


class _StaticContextBuilder:
    def __init__(self, context: TurnContext) -> None:
        self._context = context

    async def build(self, turn_input: TurnInput) -> TurnContext:
        return self._context


async def _load_conversation_or_404(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    row = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return row


async def _build_real_agent_runtime_context(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation: Conversation,
) -> TurnContext:
    inbound_text = await _latest_inbound_text(session, conversation.id)
    if not inbound_text:
        inbound_text = await _latest_message_text(session, conversation.id)
    if not inbound_text:
        raise HTTPException(status.HTTP_409_CONFLICT, "conversation has no messages to answer")
    provider = UnifiedKnowledgeProvider(session)
    return await ContextBuilder(session=session, knowledge_provider=provider).build(
        TurnInput(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation.id),
            inbound_text=inbound_text,
            metadata={
                "agent_id": str(conversation.assigned_agent_id)
                if conversation.assigned_agent_id
                else None,
                "manual_agent_runtime_v2": True,
            },
        )
    )


async def _latest_inbound_text(session: AsyncSession, conversation_id: UUID) -> str | None:
    return (
        await session.execute(
            select(MessageRow.text)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.direction == "inbound",
                MessageRow.deleted_at.is_(None),
            )
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_message_text(session: AsyncSession, conversation_id: UUID) -> str | None:
    return (
        await session.execute(
            select(MessageRow.text)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.deleted_at.is_(None),
            )
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_inbound_row(
    session: AsyncSession,
    conversation_id: UUID,
) -> tuple[UUID | None, datetime | None]:
    row = (
        await session.execute(
            select(MessageRow.id, MessageRow.sent_at)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.direction == "inbound",
                MessageRow.deleted_at.is_(None),
            )
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None
    return row.id, row.sent_at


async def _conversation_is_paused(
    session: AsyncSession,
    conversation_id: UUID,
) -> bool:
    return bool(
        (
            await session.execute(
                select(ConversationStateRow.bot_paused).where(
                    ConversationStateRow.conversation_id == conversation_id
                )
            )
        ).scalar_one_or_none()
    )


async def _has_open_handoff(session: AsyncSession, conversation_id: UUID) -> bool:
    return bool(
        (
            await session.execute(
                select(HumanHandoff.id)
                .where(
                    HumanHandoff.conversation_id == conversation_id,
                    HumanHandoff.status == "open",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    )


async def _ensure_send_allowed(session: AsyncSession, conversation: Conversation) -> None:
    if conversation.status not in {"active", "open"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "conversation is not active")
    if await _conversation_is_paused(session, conversation.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "conversation is paused by human")
    if await _has_open_handoff(session, conversation.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "conversation has an open human handoff")
    _message_id, last_inbound_at = await _latest_inbound_row(session, conversation.id)
    if last_inbound_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "conversation has no inbound message")
    if datetime.now(UTC) - last_inbound_at > timedelta(hours=24):
        raise HTTPException(status.HTTP_409_CONFLICT, "outside WhatsApp 24h window")


async def _run_agent_runtime_v2_for_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    model_provider_allowed: bool | None = None,
    workflow_events_real: bool = False,
    rollout_decisions: list[RolloutDecision] | None = None,
) -> tuple[TurnContext, TurnOutput]:
    context = await _build_real_agent_runtime_context(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
    )
    rollout_metadata = _rollout_debug_payload(rollout_decisions or [])
    if model_provider_allowed is not None or rollout_metadata:
        context = context.model_copy(
            update={
                "metadata": {
                    **context.metadata,
                    "rollout": {
                        **rollout_metadata,
                        "model_provider_allowed": model_provider_allowed,
                    },
                }
            }
        )
    runtime = _build_conversation_agent_runtime(context)
    try:
        output = await runtime.run_turn(
            TurnInput(
                tenant_id=str(tenant_id),
                conversation_id=str(conversation.id),
                inbound_text=context.inbound_text,
                metadata=context.metadata,
            )
        )
    except PolicyValidationError as exc:
        policy_issues = [
            {"code": issue.code, "message": issue.message}
            for issue in exc.issues
        ]
        await AgentWorkflowEventEmitter().emit_policy_blocked(
            session,
            context=context,
            policy_issues=policy_issues,
            dry_run=not workflow_events_real,
            emit_real=workflow_events_real,
        )
        await _record_agent_runtime_v2_trace(
            session,
            tenant_id=tenant_id,
            conversation=conversation,
            context=None,
            output=None,
            mode="policy_error",
            policy_issues=policy_issues,
            action_results=[],
            outbound_messages=[],
            rollout_decisions=rollout_decisions or [],
        )
        await session.commit()
        raise HTTPException(
            422,
            {
                "message": "agent_runtime_v2 output failed policy validation",
                "issues": policy_issues,
            },
        ) from exc
    return context, output


async def _record_agent_runtime_v2_trace(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    context: TurnContext | None,
    output: TurnOutput | None,
    mode: str,
    policy_issues: list[dict],
    action_results: list[dict],
    outbound_messages: list[str],
    rollout_decisions: list[RolloutDecision] | None = None,
    pilot_decision: PilotDecision | None = None,
) -> TurnTrace:
    rollout_payload = _rollout_debug_payload(rollout_decisions or [])
    pilot_payload = (
        pilot_decision.trace_payload()
        if pilot_decision is not None and pilot_decision.policy.get("configured")
        else None
    )
    inbound_message_id, _last_inbound_at = await _latest_inbound_row(session, conversation.id)
    turn_number = (
        await session.execute(
            select(func.coalesce(func.max(TurnTrace.turn_number), 0) + 1).where(
                TurnTrace.conversation_id == conversation.id
            )
        )
    ).scalar_one()
    trace = TurnTrace(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        turn_number=int(turn_number),
        inbound_message_id=inbound_message_id,
        inbound_text=context.inbound_text if context else None,
        state_before={
            "conversation_id": str(conversation.id),
            "current_stage": conversation.current_stage,
            "status": conversation.status,
            "context_summary": _agent_runtime_v2_context_summary(context) if context else None,
        },
        state_after={
            "agent_runtime_v2": True,
            "mode": mode,
            "policy_valid": not policy_issues,
            "actions_dry_run": _actions_were_dry_run(action_results),
            "rollout": rollout_payload,
            "pilot": pilot_payload,
            "action_results": action_results,
        },
        composer_input={
            "runtime": "agent_runtime_v2",
            "context_summary": _agent_runtime_v2_context_summary(context) if context else None,
        },
        composer_output=output.model_dump(mode="json") if output else None,
        composer_provider=(
            "openai"
            if output and output.trace_metadata.get("provider") == "openai"
            else "fallback"
        ),
        outbound_messages=outbound_messages or None,
        total_latency_ms=(
            int(output.trace_metadata["latency_ms"])
            if output and isinstance(output.trace_metadata.get("latency_ms"), int)
            else None
        ),
        errors=policy_issues or None,
        bot_paused=await _conversation_is_paused(session, conversation.id),
        router_trigger=f"agent_runtime_v2_{mode}",
        raw_llm_response=(
            output.model_dump_json() if output and output.trace_metadata.get("provider") else None
        ),
        agent_id=conversation.assigned_agent_id,
        kb_evidence={
            "citations": [
                citation.model_dump(mode="json")
                for citation in (output.knowledge_citations if output else [])
            ],
            "retrieval": context.metadata.get("knowledge", {}) if context else {},
            "pilot": pilot_payload,
        },
        rules_evaluated=[
            {
                "feature_flag": "agent_runtime_v2_enabled",
                "passed": True,
            },
            *[
                {
                    "rollout_capability": decision.capability,
                    "passed": decision.allowed,
                    "reasons": decision.reasons,
                }
                for decision in (rollout_decisions or [])
            ],
            {
                "rule": "policy_valid",
                "passed": not policy_issues,
            },
        ],
    )
    session.add(trace)
    await session.flush()
    return trace


def _agent_runtime_v2_context_summary(context: TurnContext | None) -> str:
    if context is None:
        return "context=unavailable"
    return (
        f"tenant={context.tenant_id}; conversation={context.conversation_id}; "
        f"messages={len(context.messages)}; citations={len(context.knowledge_citations)}; "
        f"stage={context.lifecycle.stage or 'none'}; agent="
        f"{context.active_agent.id if context.active_agent else 'none'}"
    )


def _actions_were_dry_run(action_results: list[dict]) -> bool:
    if not action_results:
        return True
    return all(
        bool((result.get("trace_metadata") or {}).get("dry_run"))
        for result in action_results
    )


def _rollout_debug_payload(decisions: list[RolloutDecision]) -> dict:
    return {
        decision.capability: decision.model_dump(mode="json")
        for decision in decisions
    }


def _agent_runtime_v2_response(
    *,
    output: TurnOutput,
    context: TurnContext,
    trace: TurnTrace,
    policy_issues: list[dict],
    action_results: list[dict],
    workflow_events: list[dict] | None = None,
    mode: str,
    message_id: UUID | None = None,
    outbox_id: UUID | None = None,
    pilot_decision: PilotDecision | None = None,
) -> AgentRuntimeV2ConversationResponse | AgentRuntimeV2SendResponse:
    payload = {
        "final_message": output.final_message,
        "knowledge_citations": [
            citation.model_dump(mode="json") for citation in output.knowledge_citations
        ],
        "field_updates": [update.model_dump(mode="json") for update in output.field_updates],
        "lifecycle_update": (
            output.lifecycle_update.model_dump(mode="json")
            if output.lifecycle_update is not None
            else None
        ),
        "actions": [action.model_dump(mode="json") for action in output.actions],
        "confidence": output.confidence,
        "needs_human": output.needs_human,
        "risk_flags": list(output.risk_flags),
        "trace_metadata": output.trace_metadata,
        "debug": {
            "mode": mode,
            "trace_id": str(trace.id),
            "context_summary": _agent_runtime_v2_context_summary(context),
            "retrieval": context.metadata.get("knowledge", {}),
            "rollout": context.metadata.get("rollout", {}),
            "pilot": pilot_decision.trace_payload() if pilot_decision else None,
            "policy": {"valid": not policy_issues, "issues": policy_issues},
            "actions": {"results": action_results},
            "workflow_events": workflow_events or [],
            "side_effects": {
                "persisted_messages": message_id is not None,
                "staged_outbox": outbox_id is not None,
                "sent_whatsapp_direct": False,
            },
        },
    }
    if mode == "send":
        return AgentRuntimeV2SendResponse(
            **payload,
            message_id=message_id,
            outbox_id=outbox_id,
        )
    return AgentRuntimeV2ConversationResponse(**payload)


@router.post(
    "/{conversation_id}/agent-runtime-v2/preview",
    response_model=AgentRuntimeV2ConversationResponse,
)
async def preview_agent_runtime_v2_for_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRuntimeV2ConversationResponse:
    _agent_runtime_v2_settings_or_403()
    conversation = await _load_conversation_or_404(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    rollout = RolloutPolicyService(session)
    preview_decision = await rollout.can_preview(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    if not preview_decision.allowed:
        raise _rollout_http_error(preview_decision)
    model_provider_decision = await rollout.can_use_model_provider(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    context, output = await _run_agent_runtime_v2_for_conversation(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
        model_provider_allowed=model_provider_decision.allowed,
        rollout_decisions=[preview_decision, model_provider_decision],
    )
    policy_issues = [
        {"code": issue.code, "message": issue.message}
        for issue in PolicyValidator(
            action_registry_for_agent(context.active_agent)
        ).validate(output)
    ]
    trace = await _record_agent_runtime_v2_trace(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
        context=context,
        output=output,
        mode="preview",
        policy_issues=policy_issues,
        action_results=[],
        outbound_messages=[],
        rollout_decisions=[preview_decision, model_provider_decision],
    )
    workflow_events = await AgentWorkflowEventEmitter().emit_for_turn(
        session,
        context=context,
        output=output,
        action_results=[],
        policy_issues=policy_issues,
        dry_run=True,
        emit_real=False,
    )
    await session.commit()
    return _agent_runtime_v2_response(
        output=output,
        context=context,
        trace=trace,
        policy_issues=policy_issues,
        action_results=[],
        workflow_events=[event.model_dump() for event in workflow_events],
        mode="preview",
    )


@router.post(
    "/{conversation_id}/agent-runtime-v2/shadow",
    response_model=AgentRuntimeV2ConversationResponse,
)
async def shadow_agent_runtime_v2_for_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRuntimeV2ConversationResponse:
    del user
    _agent_runtime_v2_settings_or_403()
    conversation = await _load_conversation_or_404(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    rollout = RolloutPolicyService(session)
    shadow_decision = await rollout.can_shadow(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    if not shadow_decision.allowed:
        raise _rollout_http_error(shadow_decision)
    model_provider_decision = await rollout.can_use_model_provider(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    context, output = await _run_agent_runtime_v2_for_conversation(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
        model_provider_allowed=model_provider_decision.allowed,
        workflow_events_real=False,
        rollout_decisions=[shadow_decision, model_provider_decision],
    )
    policy_issues = [
        {"code": issue.code, "message": issue.message}
        for issue in PolicyValidator(
            action_registry_for_agent(context.active_agent)
        ).validate(output)
    ]
    trace = await _record_agent_runtime_v2_trace(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
        context=context,
        output=output,
        mode="shadow",
        policy_issues=policy_issues,
        action_results=[],
        outbound_messages=[],
        rollout_decisions=[shadow_decision, model_provider_decision],
    )
    workflow_events = await AgentWorkflowEventEmitter().emit_for_turn(
        session,
        context=context,
        output=output,
        action_results=[],
        policy_issues=policy_issues,
        dry_run=True,
        emit_real=False,
    )
    await session.commit()
    return _agent_runtime_v2_response(
        output=output,
        context=context,
        trace=trace,
        policy_issues=policy_issues,
        action_results=[],
        workflow_events=[event.model_dump() for event in workflow_events],
        mode="shadow",
    )


@router.post(
    "/{conversation_id}/agent-runtime-v2/send",
    response_model=AgentRuntimeV2SendResponse,
)
async def send_agent_runtime_v2_for_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRuntimeV2SendResponse:
    del user
    _agent_runtime_v2_settings_or_403()
    conversation = await _load_conversation_or_404(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    rollout = RolloutPolicyService(session)
    send_decision = await rollout.can_send(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    if not send_decision.allowed:
        raise _rollout_http_error(send_decision)
    actions_decision = await rollout.can_execute_actions(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    workflow_events_decision = await rollout.can_emit_workflow_events(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    model_provider_decision = await rollout.can_use_model_provider(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    rollout_decisions = [
        send_decision,
        actions_decision,
        workflow_events_decision,
        model_provider_decision,
    ]
    pilot_decision = await AgentRuntimeV2PilotPolicyService(session).can_send(
        tenant_id=tenant_id,
        agent_id=conversation.assigned_agent_id,
        channel_id=conversation.channel,
    )
    if not pilot_decision.allowed:
        await _record_agent_runtime_v2_trace(
            session,
            tenant_id=tenant_id,
            conversation=conversation,
            context=None,
            output=None,
            mode="pilot_blocked",
            policy_issues=[
                {"code": "pilot_policy_blocked", "message": reason}
                for reason in pilot_decision.reasons
            ],
            action_results=[],
            outbound_messages=[],
            rollout_decisions=rollout_decisions,
            pilot_decision=pilot_decision,
        )
        await session.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "message": "agent_runtime_v2 pilot policy blocks send",
                "pilot": pilot_decision.trace_payload(),
            },
        )
    pilot_configured = bool(pilot_decision.policy.get("configured"))
    actions_real_allowed = actions_decision.allowed and not (
        pilot_configured and pilot_decision.policy.get("actions_dry_run_required", True)
    )
    workflow_events_real_allowed = workflow_events_decision.allowed and not (
        pilot_configured
        and pilot_decision.policy.get("workflow_events_dry_run_required", True)
    )
    await _ensure_send_allowed(session, conversation)
    context, output = await _run_agent_runtime_v2_for_conversation(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
        model_provider_allowed=model_provider_decision.allowed,
        workflow_events_real=workflow_events_real_allowed,
        rollout_decisions=rollout_decisions,
    )
    if not output.final_message.strip():
        raise HTTPException(422, "final_message is empty")
    policy_issues = [
        {"code": issue.code, "message": issue.message}
        for issue in PolicyValidator(
            action_registry_for_agent(context.active_agent)
        ).validate(output)
    ]
    if policy_issues:
        await AgentWorkflowEventEmitter().emit_for_turn(
            session,
            context=context,
            output=output,
            action_results=[],
            policy_issues=policy_issues,
            dry_run=not workflow_events_real_allowed,
            emit_real=workflow_events_real_allowed,
        )
        trace = await _record_agent_runtime_v2_trace(
            session,
            tenant_id=tenant_id,
            conversation=conversation,
            context=context,
            output=output,
            mode="send_blocked",
            policy_issues=policy_issues,
            action_results=[],
            outbound_messages=[],
            rollout_decisions=rollout_decisions,
            pilot_decision=pilot_decision,
        )
        await session.commit()
        raise HTTPException(
            422,
            {
                "message": "agent_runtime_v2 output failed policy validation",
                "trace_id": str(trace.id),
            },
        )
    action_results = await PostTurnActionExecutor(
        dry_run=not actions_real_allowed,
        session=session,
        max_actions_per_turn=send_decision.policy.get("max_actions_per_turn"),
        require_runtime_enabled=True,
    ).execute(output, context=context)
    workflow_events = await AgentWorkflowEventEmitter().emit_for_turn(
        session,
        context=context,
        output=output,
        action_results=action_results,
        policy_issues=[],
        dry_run=not workflow_events_real_allowed,
        emit_real=workflow_events_real_allowed,
    )
    now = datetime.now(UTC)
    customer_phone = (
        await session.execute(
            select(Customer.phone_e164).where(Customer.id == conversation.customer_id)
        )
    ).scalar_one()
    outbound = OutboundMessage(
        tenant_id=str(tenant_id),
        to_phone_e164=customer_phone,
        text=output.final_message,
        idempotency_key=f"agent-runtime-v2:{conversation.id}:{int(now.timestamp() * 1000)}",
        metadata={
            "source": "agent_runtime_v2",
            "conversation_id": str(conversation.id),
            "actions_dry_run": not actions_real_allowed,
            "workflow_events_dry_run": not workflow_events_real_allowed,
            "rollout": _rollout_debug_payload(rollout_decisions),
            "pilot": pilot_decision.trace_payload(),
        },
    )
    outbox_id = await stage_outbound(session, outbound)
    session.add(
        MessageRow(
            id=outbox_id,
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            direction="outbound",
            text=output.final_message,
            sent_at=now,
            delivery_status="queued",
            metadata_json={
                "source": "agent_runtime_v2",
                "trace_metadata": output.trace_metadata,
                "pilot": pilot_decision.trace_payload(),
            },
        )
    )
    await session.execute(
        update(Conversation).where(Conversation.id == conversation.id).values(last_activity_at=now)
    )
    trace = await _record_agent_runtime_v2_trace(
        session,
        tenant_id=tenant_id,
        conversation=conversation,
        context=context,
        output=output,
        mode="send",
        policy_issues=[],
        action_results=[result.model_dump(mode="json") for result in action_results],
        outbound_messages=[output.final_message],
        rollout_decisions=rollout_decisions,
        pilot_decision=pilot_decision,
    )
    await session.commit()
    return _agent_runtime_v2_response(
        output=output,
        context=context,
        trace=trace,
        policy_issues=[],
        action_results=[result.model_dump(mode="json") for result in action_results],
        workflow_events=[event.model_dump() for event in workflow_events],
        mode="send",
        message_id=outbox_id,
        outbox_id=outbox_id,
        pilot_decision=pilot_decision,
    )


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
    idempotency_key = f"intervene:{conversation_id}:{int(now.timestamp() * 1000)}"
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
        update(Conversation).where(Conversation.id == conversation_id).values(last_activity_at=now)
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


@router.post(
    "/{conversation_id}/force-summary",
    response_model=ProcessingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
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
    status: str | None = Field(
        default=None,
        description="Conversation status. Use 'resolved'/'closed' to close.",
    )
    close_reason: str | None = Field(default=None, max_length=200)
    close_category: str | None = Field(default=None, max_length=60)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"active", "resolved", "closed", "archived"}
        if value not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return value

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
            select(Conversation.id, Conversation.current_stage, Conversation.status).where(
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
    stage_before: str | None = None
    stage_after: str | None = None
    fields = body.model_fields_set

    if "current_stage" in fields and body.current_stage is not None:
        stage_ids = await _active_pipeline_stage_ids(session, tenant_id)
        if stage_ids is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "tenant has no active pipeline")
        if body.current_stage not in stage_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown pipeline stage")
        values["current_stage"] = body.current_stage
        update_stage_entered_at = body.current_stage != own.current_stage
        if update_stage_entered_at:
            stage_before = own.current_stage
            stage_after = body.current_stage

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

    tags_before: list[str] = []
    tags_after: list[str] = []
    if "tags" in fields and body.tags is not None:
        # Pre-image fetch so we can diff added vs removed cleanly. Keeps the
        # event payload deterministic regardless of order in the new list.
        prior_tags = (
            await session.execute(
                select(Conversation.tags).where(Conversation.id == conversation_id)
            )
        ).scalar_one_or_none()
        tags_before = list(prior_tags or [])
        tags_after = list(body.tags)
        values["tags"] = body.tags

    closing = False
    closed_states = {"resolved", "closed", "archived"}
    if "status" in fields and body.status is not None:
        values["status"] = body.status
        # "Closing" means transitioning *into* a terminal status from a
        # non-terminal one. Re-PATCHing the same closed status doesn't
        # re-fire the trigger.
        closing = body.status in closed_states and own.status not in closed_states

    if values:
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(**values)
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
        if stage_before is not None and stage_after is not None:
            await emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.STAGE_EXITED,
                payload={
                    "from": stage_before,
                    "to": stage_after,
                    "by": str(user.user_id),
                },
            )
            await emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.STAGE_ENTERED,
                payload={
                    "from": stage_before,
                    "to": stage_after,
                    "by": str(user.user_id),
                },
            )
            await emit_stage_changed(
                session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                from_stage=stage_before,
                to_stage=stage_after,
                from_label=stage_before,
                to_label=stage_after,
                reason="manual_stage_move",
            )
        if closing:
            # Separate trigger event so workflows can react to the transition
            # specifically. The payload carries the operator-supplied reason
            # and category, plus a fixed "source: user" because the API path
            # is always user-driven (bot/workflow-driven closes will set this
            # to the right source when they're added).
            await emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.CONVERSATION_CLOSED,
                payload={
                    "status": body.status,
                    "reason": body.close_reason,
                    "category": body.close_category,
                    "source": "user",
                    "by": str(user.user_id),
                },
            )
        # Tag diff: fire one event per side that changed. The engine matcher
        # filters by ``action`` and intersects ``tags`` against ``changed_tags``.
        if "tags" in fields:
            added = sorted(set(tags_after) - set(tags_before))
            removed = sorted(set(tags_before) - set(tags_after))
            if added:
                await emitter.emit(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    event_type=EventType.TAG_UPDATED,
                    payload={
                        "action": "added",
                        "changed_tags": added,
                        "current_tags": tags_after,
                        "by": str(user.user_id),
                    },
                )
            if removed:
                await emitter.emit(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    event_type=EventType.TAG_UPDATED,
                    payload={
                        "action": "removed",
                        "changed_tags": removed,
                        "current_tags": tags_after,
                        "by": str(user.user_id),
                    },
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
    row = (
        await session.execute(
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
        )
    ).first()

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
        update(Conversation).where(Conversation.id == conversation_id).values(unread_count=0)
    )
    await session.commit()

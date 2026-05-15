"""Operator dashboard — bulk export (Phase 4 T52, simplified).

Plan T52 called for an arq job that uploads CSV to local storage and
emits an `export_ready` event. Scoped down: synchronous streaming CSV
response. Same operator-facing UX (click → file downloads), zero
worker infrastructure.

This trades immediate cost (operator waits ~seconds for large tenants)
against immediate complexity. If exports get slow, swap in the arq
flow described in the plan as Phase 4.5.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.session import get_db_session

router = APIRouter()


def _date_to_dt(d: date | None, *, end_of_day: bool = False) -> datetime | None:
    if d is None:
        return None
    return datetime.combine(d, time.max if end_of_day else time.min, tzinfo=timezone.utc)


@router.get("/conversations.csv")
async def export_conversations(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    stmt = (
        select(
            Conversation.id,
            Conversation.created_at,
            Conversation.last_activity_at,
            Conversation.status,
            Conversation.current_stage,
            Customer.phone_e164,
            Customer.name,
            ConversationStateRow.total_cost_usd,
            ConversationStateRow.extracted_data,
        )
        .select_from(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(
            ConversationStateRow,
            ConversationStateRow.conversation_id == Conversation.id,
        )
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.created_at.desc())
    )
    f = _date_to_dt(from_)
    t = _date_to_dt(to, end_of_day=True)
    if f is not None:
        stmt = stmt.where(Conversation.created_at >= f)
    if t is not None:
        stmt = stmt.where(Conversation.created_at <= t)

    rows = (await session.execute(stmt)).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "conversation_id",
            "created_at",
            "last_activity_at",
            "status",
            "current_stage",
            "customer_phone",
            "customer_name",
            "total_cost_usd",
            "modelo_moto",
            "plan_credito",
            "papeleria_completa",
        ]
    )
    for r in rows:
        ed = r.extracted_data or {}

        # extracted_data values are ExtractedField dicts; pluck `.value` if present.
        def _v(k: str) -> str:
            x = ed.get(k)
            if isinstance(x, dict):
                return str(x.get("value", ""))
            return "" if x is None else str(x)

        writer.writerow(
            [
                str(r.id),
                r.created_at.isoformat() if r.created_at else "",
                r.last_activity_at.isoformat() if r.last_activity_at else "",
                r.status,
                r.current_stage,
                r.phone_e164,
                r.name or "",
                str(r.total_cost_usd or ""),
                _v("modelo_moto"),
                _v("plan_credito"),
                _v("papeleria_completa"),
            ]
        )
    buf.seek(0)

    filename = f"atendia-conversations-{datetime.now(timezone.utc).date().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/messages.csv")
async def export_messages(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    stmt = (
        select(
            MessageRow.id,
            MessageRow.conversation_id,
            MessageRow.direction,
            MessageRow.text,
            MessageRow.sent_at,
        )
        .where(MessageRow.tenant_id == tenant_id)
        .order_by(MessageRow.sent_at.desc())
    )
    f = _date_to_dt(from_)
    t = _date_to_dt(to, end_of_day=True)
    if f is not None:
        stmt = stmt.where(MessageRow.sent_at >= f)
    if t is not None:
        stmt = stmt.where(MessageRow.sent_at <= t)

    rows = (await session.execute(stmt)).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "conversation_id", "direction", "sent_at", "text"])
    for r in rows:
        writer.writerow(
            [
                str(r.id),
                str(r.conversation_id),
                r.direction,
                r.sent_at.isoformat() if r.sent_at else "",
                # CSV-safe — newlines in text become escaped by csv.writer
                r.text,
            ]
        )
    buf.seek(0)
    filename = f"atendia-messages-{datetime.now(timezone.utc).date().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

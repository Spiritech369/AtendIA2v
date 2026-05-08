"""Operator dashboard — audit log timeline (Phase 4 T49, Block J).

Reads the `events` table. Tenant-scoped: operators see their own
tenant's events; superadmins see any tenant via ?tid=. Optional ?type=
filter (single event_type) and ?from=/?to= ISO timestamps.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.event import EventRow
from atendia.db.session import get_db_session

router = APIRouter()


class AuditEvent(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    type: str
    payload: dict
    occurred_at: datetime
    trace_id: str | None
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditEvent]
    next_cursor: str | None


def _encode_cursor(ts: datetime, eid: UUID) -> str:
    raw = json.dumps({"ts": ts.isoformat(), "id": str(eid)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        obj = json.loads(decoded)
        return datetime.fromisoformat(obj["ts"]), UUID(obj["id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from e


@router.get("", response_model=AuditListResponse)
async def list_events(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    type_: str | None = Query(None, alias="type"),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> AuditListResponse:
    stmt = (
        select(EventRow)
        .where(EventRow.tenant_id == tenant_id)
        .order_by(EventRow.occurred_at.desc(), EventRow.id.desc())
        .limit(limit + 1)
    )
    if type_ is not None:
        stmt = stmt.where(EventRow.type == type_)
    if from_ is not None:
        stmt = stmt.where(EventRow.occurred_at >= from_)
    if to is not None:
        stmt = stmt.where(EventRow.occurred_at <= to)
    if cursor is not None:
        cur_ts, cur_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                EventRow.occurred_at < cur_ts,
                and_(
                    EventRow.occurred_at == cur_ts,
                    EventRow.id < cur_id,
                ),
            )
        )

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        AuditEvent(
            id=e.id,
            tenant_id=e.tenant_id,
            conversation_id=e.conversation_id,
            type=e.type,
            payload=e.payload,
            occurred_at=e.occurred_at,
            trace_id=e.trace_id,
            created_at=e.created_at,
        )
        for e in page
    ]
    next_cursor = (
        _encode_cursor(page[-1].occurred_at, page[-1].id) if has_more and page else None
    )
    return AuditListResponse(items=items, next_cursor=next_cursor)

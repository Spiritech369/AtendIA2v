"""Operator dashboard — handoffs queue + assign/resolve.

Phase 4 T20-T21. Tenant-scoped. The list returns the full structured
HandoffSummary (`human_handoffs.payload`, populated by Phase 3c.2
escalations) so the dashboard can render reason, customer context,
and suggested-next-action without an extra fetch.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.api._handoffs.command_center import router as _handoff_command_center_router
from atendia.config import get_settings
from atendia.db.models.lifecycle import HumanHandoff
from atendia.db.session import get_db_session
from atendia.realtime.publisher import publish_event

router = APIRouter()
router.include_router(_handoff_command_center_router)


# ---------- Response shapes ----------


class HandoffItem(BaseModel):
    id: UUID
    conversation_id: UUID
    tenant_id: UUID
    reason: str
    payload: dict | None
    assigned_user_id: UUID | None
    status: str  # "open" | "assigned" | "resolved"
    requested_at: datetime
    resolved_at: datetime | None


class HandoffListResponse(BaseModel):
    items: list[HandoffItem]
    next_cursor: str | None


class AssignBody(BaseModel):
    user_id: UUID


class ResolveBody(BaseModel):
    note: str | None = None


# ---------- Cursor helpers (same scheme as conversations_routes) ----------


def _encode_cursor(ts: datetime, hid: UUID) -> str:
    raw = json.dumps({"ts": ts.isoformat(), "id": str(hid)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        obj = json.loads(decoded)
        return datetime.fromisoformat(obj["ts"]), UUID(obj["id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from e


# ---------- Routes ----------


@router.get("", response_model=HandoffListResponse)
async def list_handoffs(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    handoff_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> HandoffListResponse:
    stmt = (
        select(HumanHandoff)
        .where(HumanHandoff.tenant_id == tenant_id)
        .order_by(HumanHandoff.requested_at.desc(), HumanHandoff.id.desc())
        .limit(limit + 1)
    )
    if handoff_status is not None:
        stmt = stmt.where(HumanHandoff.status == handoff_status)
    if cursor is not None:
        cur_ts, cur_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                HumanHandoff.requested_at < cur_ts,
                and_(
                    HumanHandoff.requested_at == cur_ts,
                    HumanHandoff.id < cur_id,
                ),
            )
        )

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        HandoffItem(
            id=h.id,
            conversation_id=h.conversation_id,
            tenant_id=h.tenant_id,
            reason=h.reason,
            payload=h.payload,
            assigned_user_id=h.assigned_user_id,
            status=h.status,
            requested_at=h.requested_at,
            resolved_at=h.resolved_at,
        )
        for h in page
    ]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.requested_at, last.id)

    return HandoffListResponse(items=items, next_cursor=next_cursor)


async def _get_handoff_in_tenant(
    session: AsyncSession, handoff_id: UUID, tenant_id: UUID
) -> HumanHandoff:
    h = (
        await session.execute(
            select(HumanHandoff).where(
                HumanHandoff.id == handoff_id,
                HumanHandoff.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "handoff not found")
    return h


async def _publish_handoff_event(
    request: Request, *, tenant_id: UUID, conversation_id: UUID, event_type: str
) -> None:
    """Best-effort live notification — failure to publish doesn't block the
    state change. The dashboard will still see the new state on next
    invalidate-driven re-fetch."""
    try:
        redis = Redis.from_url(get_settings().redis_url)
        try:
            await publish_event(
                redis,
                tenant_id=str(tenant_id),
                conversation_id=str(conversation_id),
                event={"type": event_type},
            )
        finally:
            await redis.aclose()
    except Exception:  # pragma: no cover — non-critical path
        pass


@router.post("/{handoff_id}/assign", response_model=HandoffItem)
async def assign_handoff(
    handoff_id: UUID,
    body: AssignBody,
    request: Request,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> HandoffItem:
    h = await _get_handoff_in_tenant(session, handoff_id, tenant_id)
    await session.execute(
        update(HumanHandoff)
        .where(HumanHandoff.id == handoff_id)
        .values(assigned_user_id=body.user_id, status="assigned")
    )
    await session.commit()
    await session.refresh(h)
    await _publish_handoff_event(
        request,
        tenant_id=tenant_id,
        conversation_id=h.conversation_id,
        event_type="handoff_assigned",
    )
    return HandoffItem(
        id=h.id,
        conversation_id=h.conversation_id,
        tenant_id=h.tenant_id,
        reason=h.reason,
        payload=h.payload,
        assigned_user_id=h.assigned_user_id,
        status=h.status,
        requested_at=h.requested_at,
        resolved_at=h.resolved_at,
    )


@router.post("/{handoff_id}/resolve", response_model=HandoffItem)
async def resolve_handoff(
    handoff_id: UUID,
    body: ResolveBody,
    request: Request,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> HandoffItem:
    h = await _get_handoff_in_tenant(session, handoff_id, tenant_id)

    # Merge the optional `note` into payload so the audit trail is one row,
    # not split between human_handoffs + a separate notes table.
    new_payload = dict(h.payload or {})
    if body.note:
        new_payload["resolution_note"] = body.note

    await session.execute(
        update(HumanHandoff)
        .where(HumanHandoff.id == handoff_id)
        .values(
            status="resolved",
            resolved_at=datetime.now(UTC),
            payload=new_payload or None,
        )
    )
    await session.commit()
    await session.refresh(h)
    await _publish_handoff_event(
        request,
        tenant_id=tenant_id,
        conversation_id=h.conversation_id,
        event_type="handoff_resolved",
    )
    return HandoffItem(
        id=h.id,
        conversation_id=h.conversation_id,
        tenant_id=h.tenant_id,
        reason=h.reason,
        payload=h.payload,
        assigned_user_id=h.assigned_user_id,
        status=h.status,
        requested_at=h.requested_at,
        resolved_at=h.resolved_at,
    )

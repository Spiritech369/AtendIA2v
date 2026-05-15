"""Field suggestions — list per customer, accept, reject.

Two routers because list is per-customer and accept/reject are by
suggestion id. Both are tenant-scoped + operator+.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.customer import Customer
from atendia.db.models.field_suggestion import FieldSuggestion
from atendia.db.session import get_db_session

per_customer_router = APIRouter()
actions_router = APIRouter()


class FieldSuggestionOut(BaseModel):
    id: UUID
    customer_id: UUID
    conversation_id: UUID | None
    turn_number: int | None
    key: str
    suggested_value: str
    confidence: Decimal
    evidence_text: str | None
    status: str
    created_at: datetime
    decided_at: datetime | None


def _to_out(row: FieldSuggestion) -> FieldSuggestionOut:
    return FieldSuggestionOut(
        id=row.id,
        customer_id=row.customer_id,
        conversation_id=row.conversation_id,
        turn_number=row.turn_number,
        key=row.key,
        suggested_value=row.suggested_value,
        confidence=row.confidence,
        evidence_text=row.evidence_text,
        status=row.status,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@per_customer_router.get("", response_model=list[FieldSuggestionOut])
async def list_field_suggestions(
    customer_id: UUID,
    status_filter: str = Query("pending", alias="status"),
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[FieldSuggestionOut]:
    rows = (
        (
            await session.execute(
                select(FieldSuggestion)
                .where(
                    FieldSuggestion.tenant_id == tenant_id,
                    FieldSuggestion.customer_id == customer_id,
                    FieldSuggestion.status == status_filter,
                )
                .order_by(FieldSuggestion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rows]


async def _load_pending(
    session: AsyncSession, suggestion_id: UUID, tenant_id: UUID
) -> FieldSuggestion:
    row = (
        await session.execute(
            select(FieldSuggestion).where(
                FieldSuggestion.id == suggestion_id,
                FieldSuggestion.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "suggestion not found")
    if row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"suggestion is already {row.status}",
        )
    return row


@actions_router.post("/{suggestion_id}/accept", response_model=FieldSuggestionOut)
async def accept_field_suggestion(
    suggestion_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> FieldSuggestionOut:
    sugg = await _load_pending(session, suggestion_id, tenant_id)
    customer = (
        await session.execute(select(Customer).where(Customer.id == sugg.customer_id))
    ).scalar_one()
    next_attrs = dict(customer.attrs or {})
    next_attrs[sugg.key] = sugg.suggested_value
    customer.attrs = next_attrs
    sugg.status = "accepted"
    sugg.decided_at = datetime.now(UTC)
    sugg.decided_by_user_id = user.user_id
    await session.commit()
    await session.refresh(sugg)
    return _to_out(sugg)


@actions_router.post("/{suggestion_id}/reject", response_model=FieldSuggestionOut)
async def reject_field_suggestion(
    suggestion_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> FieldSuggestionOut:
    sugg = await _load_pending(session, suggestion_id, tenant_id)
    sugg.status = "rejected"
    sugg.decided_at = datetime.now(UTC)
    sugg.decided_by_user_id = user.user_id
    await session.commit()
    await session.refresh(sugg)
    return _to_out(sugg)

"""Operator dashboard — customers search + detail (Phase 4 T38-T39).

Search by phone substring OR name substring (case-insensitive). Tenant
scoped. Detail returns the customer + all their conversations + a
summary of total cost across conversations.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.session import get_db_session

router = APIRouter()


class CustomerListItem(BaseModel):
    id: UUID
    tenant_id: UUID
    phone_e164: str
    name: str | None
    created_at: datetime
    conversation_count: int


class CustomerListResponse(BaseModel):
    items: list[CustomerListItem]


class ConversationSummary(BaseModel):
    id: UUID
    current_stage: str
    status: str
    last_activity_at: datetime
    total_cost_usd: Decimal


class CustomerDetail(BaseModel):
    id: UUID
    tenant_id: UUID
    phone_e164: str
    name: str | None
    attrs: dict
    created_at: datetime
    conversations: list[ConversationSummary]
    last_extracted_data: dict
    total_cost_usd: Decimal


class CustomerPatch(BaseModel):
    name: str | None = None
    attrs: dict | None = None


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    q: str | None = Query(None, description="phone or name substring"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerListResponse:
    conv_count = (
        select(
            Conversation.customer_id,
            func.count(Conversation.id).label("n"),
        )
        .group_by(Conversation.customer_id)
        .subquery()
    )

    stmt = (
        select(
            Customer.id,
            Customer.tenant_id,
            Customer.phone_e164,
            Customer.name,
            Customer.created_at,
            func.coalesce(conv_count.c.n, 0).label("conversation_count"),
        )
        .select_from(Customer)
        .outerjoin(conv_count, conv_count.c.customer_id == Customer.id)
        .where(Customer.tenant_id == tenant_id)
        .order_by(Customer.created_at.desc())
        .limit(limit)
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Customer.phone_e164.ilike(like),
                Customer.name.ilike(like),
            )
        )

    rows = (await session.execute(stmt)).all()
    return CustomerListResponse(
        items=[
            CustomerListItem(
                id=r.id,
                tenant_id=r.tenant_id,
                phone_e164=r.phone_e164,
                name=r.name,
                created_at=r.created_at,
                conversation_count=r.conversation_count,
            )
            for r in rows
        ]
    )


@router.get("/{customer_id}", response_model=CustomerDetail)
async def get_customer(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    cust = (
        await session.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")

    convs_rows = (
        await session.execute(
            select(
                Conversation.id,
                Conversation.current_stage,
                Conversation.status,
                Conversation.last_activity_at,
                ConversationStateRow.total_cost_usd,
                ConversationStateRow.extracted_data,
            )
            .select_from(Conversation)
            .outerjoin(
                ConversationStateRow,
                ConversationStateRow.conversation_id == Conversation.id,
            )
            .where(Conversation.customer_id == customer_id)
            .order_by(Conversation.last_activity_at.desc())
        )
    ).all()

    conversations = [
        ConversationSummary(
            id=r.id,
            current_stage=r.current_stage,
            status=r.status,
            last_activity_at=r.last_activity_at,
            total_cost_usd=r.total_cost_usd or Decimal("0"),
        )
        for r in convs_rows
    ]
    last_extracted = (convs_rows[0].extracted_data or {}) if convs_rows else {}
    total_cost = sum(
        (r.total_cost_usd or Decimal("0") for r in convs_rows), start=Decimal("0")
    )

    return CustomerDetail(
        id=cust.id,
        tenant_id=cust.tenant_id,
        phone_e164=cust.phone_e164,
        name=cust.name,
        attrs=cust.attrs or {},
        created_at=cust.created_at,
        conversations=conversations,
        last_extracted_data=last_extracted,
        total_cost_usd=total_cost,
    )


@router.patch("/{customer_id}", response_model=CustomerDetail)
async def patch_customer(
    customer_id: UUID,
    body: CustomerPatch,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    cust = (
        await session.execute(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")

    for k, v in changes.items():
        setattr(cust, k, v)
    await session.commit()
    await session.refresh(cust)

    return await get_customer(customer_id, user, tenant_id, session)

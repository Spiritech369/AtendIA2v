from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_user
from atendia.db.models.notification import Notification
from atendia.db.session import get_db_session

router = APIRouter()


class NotificationItem(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    title: str
    body: str | None
    read: bool
    source_type: str | None
    source_id: UUID | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(False),
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationListResponse:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.user_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    rows = (await session.execute(stmt)).scalars().all()
    unread = (
        (
            await session.execute(
                select(Notification.id).where(
                    Notification.user_id == user.user_id, Notification.read.is_(False)
                )
            )
        )
        .scalars()
        .all()
    )
    return NotificationListResponse(
        items=[NotificationItem.model_validate(row, from_attributes=True) for row in rows],
        unread_count=len(unread),
    )


@router.patch("/{notification_id}/read", response_model=NotificationItem)
async def mark_notification_read(
    notification_id: UUID,
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NotificationItem:
    row = (
        await session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    row.read = True
    await session.commit()
    await session.refresh(row)
    return NotificationItem.model_validate(row, from_attributes=True)


@router.post("/read-all")
async def mark_all_notifications_read(
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user.user_id, Notification.read.is_(False))
        .values(read=True)
    )
    await session.commit()
    return {"updated": result.rowcount or 0}

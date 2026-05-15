"""Customer notes CRUD — Step 1 backend prep.

Operator notes attached to a customer. Tenant-scoped, author-tracked.
Mounted at /api/v1/customers/{customer_id}/notes in main.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.customer import Customer
from atendia.db.models.customer_note import CustomerNote
from atendia.db.models.tenant import TenantUser
from atendia.db.session import get_db_session

router = APIRouter()


class NoteOut(BaseModel):
    id: UUID
    customer_id: UUID
    tenant_id: UUID
    author_user_id: UUID | None
    author_email: str | None
    content: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


class NoteCreate(BaseModel):
    content: str
    pinned: bool = False


class NoteUpdate(BaseModel):
    content: str | None = None
    pinned: bool | None = None


async def _verify_customer_access(
    customer_id: UUID, tenant_id: UUID, session: AsyncSession
) -> None:
    exists = (
        await session.execute(
            select(Customer.id).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")


@router.get("", response_model=list[NoteOut])
async def list_notes(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[NoteOut]:
    await _verify_customer_access(customer_id, tenant_id, session)
    rows = (
        await session.execute(
            select(CustomerNote, TenantUser.email)
            .outerjoin(TenantUser, TenantUser.id == CustomerNote.author_user_id)
            .where(
                CustomerNote.customer_id == customer_id,
                CustomerNote.tenant_id == tenant_id,
            )
            .order_by(CustomerNote.pinned.desc(), CustomerNote.created_at.desc())
        )
    ).all()
    return [
        NoteOut(
            id=n.id,
            customer_id=n.customer_id,
            tenant_id=n.tenant_id,
            author_user_id=n.author_user_id,
            author_email=email,
            content=n.content,
            pinned=n.pinned,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n, email in rows
    ]


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    customer_id: UUID,
    body: NoteCreate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NoteOut:
    await _verify_customer_access(customer_id, tenant_id, session)
    note = CustomerNote(
        customer_id=customer_id,
        tenant_id=tenant_id,
        author_user_id=user.user_id,
        content=body.content,
        pinned=body.pinned,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return NoteOut(
        id=note.id,
        customer_id=note.customer_id,
        tenant_id=note.tenant_id,
        author_user_id=note.author_user_id,
        author_email=user.email,
        content=note.content,
        pinned=note.pinned,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    customer_id: UUID,
    note_id: UUID,
    body: NoteUpdate,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> NoteOut:
    note = (
        await session.execute(
            select(CustomerNote).where(
                CustomerNote.id == note_id,
                CustomerNote.customer_id == customer_id,
                CustomerNote.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")

    for k, v in changes.items():
        setattr(note, k, v)
    await session.commit()
    await session.refresh(note)
    author_email = None
    if note.author_user_id:
        author_email = (
            await session.execute(
                select(TenantUser.email).where(TenantUser.id == note.author_user_id)
            )
        ).scalar_one_or_none()
    return NoteOut(
        id=note.id,
        customer_id=note.customer_id,
        tenant_id=note.tenant_id,
        author_user_id=note.author_user_id,
        author_email=author_email,
        content=note.content,
        pinned=note.pinned,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    customer_id: UUID,
    note_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        delete(CustomerNote).where(
            CustomerNote.id == note_id,
            CustomerNote.customer_id == customer_id,
            CustomerNote.tenant_id == tenant_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    await session.commit()

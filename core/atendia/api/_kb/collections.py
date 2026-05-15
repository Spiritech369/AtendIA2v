"""GET / POST / PATCH / DELETE /api/v1/knowledge/collections — kb_collections CRUD.

Operator UI lists collections in the sidebar and uses them as a filter
across all four content types. The seed script (Task 10) writes 9
defaults; this endpoint set lets the operator add/rename/delete
custom collections beyond the defaults.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.kb_collection import KbCollection
from atendia.db.session import get_db_session

router = APIRouter()


class CollectionItem(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None


class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    description: str | None = Field(default=None, max_length=1000)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


class CollectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


def _to_item(row: KbCollection) -> CollectionItem:
    return CollectionItem(
        id=row.id,
        name=row.name,
        slug=row.slug,
        description=row.description,
        icon=row.icon,
        color=row.color,
    )


@router.get("/collections", response_model=list[CollectionItem])
async def list_collections(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[CollectionItem]:
    rows = (
        (
            await session.execute(
                select(KbCollection)
                .where(KbCollection.tenant_id == tenant_id)
                .order_by(KbCollection.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_item(r) for r in rows]


@router.post("/collections", response_model=CollectionItem, status_code=201)
async def create_collection(
    body: CollectionBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CollectionItem:
    row = KbCollection(
        tenant_id=tenant_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        icon=body.icon,
        color=body.color,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug ya existe en este tenant")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="kb.collection.created",
        payload={"id": str(row.id), "slug": row.slug, "name": row.name},
    )
    await session.commit()
    await session.refresh(row)
    return _to_item(row)


@router.patch("/collections/{collection_id}", response_model=CollectionItem)
async def update_collection(
    collection_id: UUID,
    body: CollectionPatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CollectionItem:
    row = (
        await session.execute(
            select(KbCollection).where(
                KbCollection.id == collection_id,
                KbCollection.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "colección no encontrada")
    patch_data = body.model_dump(exclude_unset=True)
    if not patch_data:
        return _to_item(row)
    await session.execute(
        update(KbCollection)
        .where(KbCollection.id == collection_id, KbCollection.tenant_id == tenant_id)
        .values(**patch_data)
    )
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="kb.collection.updated",
        payload={"id": str(collection_id), "patch": patch_data},
    )
    await session.commit()
    await session.refresh(row)
    return _to_item(row)


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        delete(KbCollection)
        .where(KbCollection.id == collection_id, KbCollection.tenant_id == tenant_id)
        .returning(KbCollection.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "colección no encontrada")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="kb.collection.deleted",
        payload={"id": str(collection_id)},
    )
    await session.commit()

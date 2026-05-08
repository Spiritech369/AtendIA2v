"""Customer field definitions + values — Step 1 backend prep.

Tenant-scoped custom fields: admins define field schemas (definitions),
operators read/write per-customer values.

Definitions mounted at /api/v1/customer-fields/definitions
Values mounted at /api/v1/customers/{customer_id}/field-values
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
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue
from atendia.db.session import get_db_session

definitions_router = APIRouter()
values_router = APIRouter()


# ── Definitions schemas ──────────────────────────────────────────────


class FieldDefOut(BaseModel):
    id: UUID
    tenant_id: UUID
    key: str
    label: str
    field_type: str
    field_options: dict | None
    ordering: int
    created_at: datetime


class FieldDefCreate(BaseModel):
    key: str
    label: str
    field_type: str
    field_options: dict | None = None
    ordering: int = 0


class FieldDefUpdate(BaseModel):
    label: str | None = None
    field_type: str | None = None
    field_options: dict | None = None
    ordering: int | None = None


# ── Definitions endpoints ────────────────────────────────────────────


@definitions_router.get("", response_model=list[FieldDefOut])
async def list_definitions(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[FieldDefOut]:
    rows = (
        await session.execute(
            select(CustomerFieldDefinition)
            .where(CustomerFieldDefinition.tenant_id == tenant_id)
            .order_by(CustomerFieldDefinition.ordering)
        )
    ).scalars().all()
    return [
        FieldDefOut(
            id=d.id,
            tenant_id=d.tenant_id,
            key=d.key,
            label=d.label,
            field_type=d.field_type,
            field_options=d.field_options,
            ordering=d.ordering,
            created_at=d.created_at,
        )
        for d in rows
    ]


@definitions_router.post(
    "", response_model=FieldDefOut, status_code=status.HTTP_201_CREATED
)
async def create_definition(
    body: FieldDefCreate,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> FieldDefOut:
    defn = CustomerFieldDefinition(
        tenant_id=tenant_id,
        key=body.key,
        label=body.label,
        field_type=body.field_type,
        field_options=body.field_options,
        ordering=body.ordering,
    )
    session.add(defn)
    await session.commit()
    await session.refresh(defn)
    return FieldDefOut(
        id=defn.id,
        tenant_id=defn.tenant_id,
        key=defn.key,
        label=defn.label,
        field_type=defn.field_type,
        field_options=defn.field_options,
        ordering=defn.ordering,
        created_at=defn.created_at,
    )


@definitions_router.patch("/{def_id}", response_model=FieldDefOut)
async def update_definition(
    def_id: UUID,
    body: FieldDefUpdate,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> FieldDefOut:
    defn = (
        await session.execute(
            select(CustomerFieldDefinition).where(
                CustomerFieldDefinition.id == def_id,
                CustomerFieldDefinition.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "field definition not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")

    for k, v in changes.items():
        setattr(defn, k, v)
    await session.commit()
    await session.refresh(defn)
    return FieldDefOut(
        id=defn.id,
        tenant_id=defn.tenant_id,
        key=defn.key,
        label=defn.label,
        field_type=defn.field_type,
        field_options=defn.field_options,
        ordering=defn.ordering,
        created_at=defn.created_at,
    )


@definitions_router.delete("/{def_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_definition(
    def_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    result = await session.execute(
        delete(CustomerFieldDefinition).where(
            CustomerFieldDefinition.id == def_id,
            CustomerFieldDefinition.tenant_id == tenant_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "field definition not found")
    await session.commit()


# ── Values schemas ───────────────────────────────────────────────────


class FieldValueOut(BaseModel):
    field_definition_id: UUID
    key: str
    value: str | None


class FieldValuePut(BaseModel):
    values: dict[str, str | None]


# ── Values endpoints ─────────────────────────────────────────────────


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


@values_router.get("", response_model=list[FieldValueOut])
async def get_field_values(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[FieldValueOut]:
    await _verify_customer_access(customer_id, tenant_id, session)
    rows = (
        await session.execute(
            select(
                CustomerFieldValue.field_definition_id,
                CustomerFieldDefinition.key,
                CustomerFieldValue.value,
            )
            .join(
                CustomerFieldDefinition,
                CustomerFieldDefinition.id == CustomerFieldValue.field_definition_id,
            )
            .where(
                CustomerFieldValue.customer_id == customer_id,
                CustomerFieldDefinition.tenant_id == tenant_id,
            )
        )
    ).all()
    return [
        FieldValueOut(
            field_definition_id=r.field_definition_id,
            key=r.key,
            value=r.value,
        )
        for r in rows
    ]


@values_router.put("")
async def put_field_values(
    customer_id: UUID,
    body: FieldValuePut,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    await _verify_customer_access(customer_id, tenant_id, session)

    defs = (
        await session.execute(
            select(CustomerFieldDefinition).where(
                CustomerFieldDefinition.tenant_id == tenant_id,
                CustomerFieldDefinition.key.in_(list(body.values.keys())),
            )
        )
    ).scalars().all()
    key_to_def = {d.key: d for d in defs}

    unknown = set(body.values.keys()) - set(key_to_def.keys())
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown field keys: {', '.join(sorted(unknown))}",
        )

    for key, val in body.values.items():
        defn = key_to_def[key]
        existing = (
            await session.execute(
                select(CustomerFieldValue).where(
                    CustomerFieldValue.customer_id == customer_id,
                    CustomerFieldValue.field_definition_id == defn.id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.value = val
        else:
            session.add(
                CustomerFieldValue(
                    customer_id=customer_id,
                    field_definition_id=defn.id,
                    value=val,
                )
            )

    await session.commit()
    return {"updated": len(body.values)}

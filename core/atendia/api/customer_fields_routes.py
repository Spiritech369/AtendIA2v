"""Customer field definitions + values — Step 1 backend prep.

Tenant-scoped custom fields: admins define field schemas (definitions),
operators read/write per-customer values.

Definitions mounted at /api/v1/customer-fields/definitions
Values mounted at /api/v1/customers/{customer_id}/field-values
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue
from atendia.db.session import get_db_session

definitions_router = APIRouter()
values_router = APIRouter()

FIELD_TYPES: frozenset[str] = frozenset(
    {
        "text",
        "select",
        "number",
        "date",
        "checkbox",
        "multiselect",
    }
)
_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


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
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    field_type: str
    field_options: dict | None = None
    ordering: int = 0

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        normalized = value.strip()
        if not _FIELD_KEY_RE.fullmatch(normalized):
            raise ValueError("key must be snake_case and start with a letter")
        return normalized

    @field_validator("field_type")
    @classmethod
    def _valid_field_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(FIELD_TYPES))}")
        return normalized

    @field_validator("field_options")
    @classmethod
    def _valid_options(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        choices = value.get("choices") or value.get("options")
        if choices is not None and (
            not isinstance(choices, list)
            or not all(isinstance(v, str) and v.strip() for v in choices)
        ):
            raise ValueError("field_options choices/options must be a non-empty string list")
        return value


class FieldDefUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    field_type: str | None = None
    field_options: dict | None = None
    ordering: int | None = None

    @field_validator("field_type")
    @classmethod
    def _valid_field_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(FIELD_TYPES))}")
        return normalized

    @field_validator("field_options")
    @classmethod
    def _valid_options(cls, value: dict | None) -> dict | None:
        return FieldDefCreate._valid_options(value)


# ── Definitions endpoints ────────────────────────────────────────────


@definitions_router.get("", response_model=list[FieldDefOut])
async def list_definitions(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[FieldDefOut]:
    rows = (
        (
            await session.execute(
                select(CustomerFieldDefinition)
                .where(CustomerFieldDefinition.tenant_id == tenant_id)
                .order_by(CustomerFieldDefinition.ordering)
            )
        )
        .scalars()
        .all()
    )
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


@definitions_router.post("", response_model=FieldDefOut, status_code=status.HTTP_201_CREATED)
async def create_definition(
    body: FieldDefCreate,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
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
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
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
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
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
    values: dict[str, str | int | float | bool | list[str] | None]


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


def _choices_for(defn: CustomerFieldDefinition) -> set[str] | None:
    opts = defn.field_options or {}
    raw = opts.get("choices") or opts.get("options")
    if not isinstance(raw, list):
        return None
    return {str(v) for v in raw}


def _canonicalize_field_value(
    defn: CustomerFieldDefinition,
    value: str | int | float | bool | list[str] | None,
) -> str | None:
    if value is None:
        return None

    field_type = defn.field_type
    choices = _choices_for(defn)

    if field_type in ("text", "select"):
        if not isinstance(value, str):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{defn.key} must be a string",
            )
        normalized = value.strip()
        if field_type == "select" and choices is not None and normalized not in choices:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{defn.key} must be one of: {', '.join(sorted(choices))}",
            )
        return normalized

    if field_type == "number":
        if isinstance(value, bool) or isinstance(value, list):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{defn.key} must be a number")
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, AttributeError):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{defn.key} must be a number"
            ) from None
        return format(number.normalize(), "f")

    if field_type == "date":
        if not isinstance(value, str):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{defn.key} must be an ISO date string",
            )
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{defn.key} must be an ISO date string",
            ) from None
        return parsed.isoformat()

    if field_type == "checkbox":
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "si", "sí"):
                return "true"
            if lowered in ("false", "0", "no"):
                return "false"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{defn.key} must be boolean")

    if field_type == "multiselect":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{defn.key} must be a list of strings",
            )
        normalized = []
        seen = set()
        for raw in value:
            item = raw.strip()
            if not item:
                continue
            if choices is not None and item not in choices:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{defn.key} must contain only: {', '.join(sorted(choices))}",
                )
            if item not in seen:
                seen.add(item)
                normalized.append(item)
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"unsupported field type for {defn.key}: {field_type}",
    )


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
        (
            await session.execute(
                select(CustomerFieldDefinition).where(
                    CustomerFieldDefinition.tenant_id == tenant_id,
                    CustomerFieldDefinition.key.in_(list(body.values.keys())),
                )
            )
        )
        .scalars()
        .all()
    )
    key_to_def = {d.key: d for d in defs}

    unknown = set(body.values.keys()) - set(key_to_def.keys())
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown field keys: {', '.join(sorted(unknown))}",
        )

    for key, val in body.values.items():
        defn = key_to_def[key]
        canonical = _canonicalize_field_value(defn, val)
        existing = (
            await session.execute(
                select(CustomerFieldValue).where(
                    CustomerFieldValue.customer_id == customer_id,
                    CustomerFieldValue.field_definition_id == defn.id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.value = canonical
        else:
            session.add(
                CustomerFieldValue(
                    customer_id=customer_id,
                    field_definition_id=defn.id,
                    value=canonical,
                )
            )

    await session.commit()
    return {"updated": len(body.values)}

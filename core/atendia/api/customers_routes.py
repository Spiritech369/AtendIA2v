"""Operator dashboard — customers search + detail (Phase 4 T38-T39).

Search by phone substring OR name substring (case-insensitive). Tenant
scoped. Detail returns the customer + all their conversations + a
summary of total cost across conversations.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.tenant import TenantUser
from atendia.db.session import get_db_session

router = APIRouter()


class CustomerListItem(BaseModel):
    id: UUID
    tenant_id: UUID
    phone_e164: str
    name: str | None
    score: int = 0
    created_at: datetime
    conversation_count: int
    effective_stage: str | None = None
    last_activity_at: datetime | None = None
    assigned_user_email: str | None = None


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
    email: str | None = None
    score: int = 0
    attrs: dict
    created_at: datetime
    conversations: list[ConversationSummary]
    last_extracted_data: dict
    total_cost_usd: Decimal


class CustomerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    email: str | None = Field(default=None, max_length=160)
    attrs: dict | None = None

    @field_validator("email")
    @classmethod
    def _strip_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ScorePatch(BaseModel):
    score: int = Field(ge=0, le=100)


class CustomerImportResult(BaseModel):
    created: int
    updated: int
    errors: list[str]


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    q: str | None = Query(None, description="phone or name substring"),
    stage: str | None = Query(None),
    assigned_user_id: UUID | None = Query(None),
    sort_by: str = Query("created_at", pattern="^(name|last_activity|score|created_at)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
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
    latest_conv_sq = (
        select(
            Conversation.customer_id.label("customer_id"),
            Conversation.current_stage.label("effective_stage"),
            Conversation.last_activity_at.label("last_activity_at"),
            Conversation.assigned_user_id.label("assigned_user_id"),
            func.row_number()
            .over(
                partition_by=Conversation.customer_id,
                order_by=Conversation.last_activity_at.desc(),
            )
            .label("rn"),
        )
        .where(Conversation.tenant_id == tenant_id, Conversation.deleted_at.is_(None))
        .subquery()
    )
    latest = select(latest_conv_sq).where(latest_conv_sq.c.rn == 1).subquery()

    stmt = (
        select(
            Customer.id,
            Customer.tenant_id,
            Customer.phone_e164,
            Customer.name,
            Customer.score,
            Customer.created_at,
            func.coalesce(conv_count.c.n, 0).label("conversation_count"),
            latest.c.effective_stage,
            latest.c.last_activity_at,
            TenantUser.email.label("assigned_user_email"),
        )
        .select_from(Customer)
        .outerjoin(conv_count, conv_count.c.customer_id == Customer.id)
        .outerjoin(latest, latest.c.customer_id == Customer.id)
        .outerjoin(TenantUser, TenantUser.id == latest.c.assigned_user_id)
        .where(Customer.tenant_id == tenant_id)
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
    if stage:
        stmt = stmt.where(latest.c.effective_stage == stage)
    if assigned_user_id:
        stmt = stmt.where(latest.c.assigned_user_id == assigned_user_id)

    sort_col = {
        "name": Customer.name,
        "last_activity": latest.c.last_activity_at,
        "score": Customer.score,
        "created_at": Customer.created_at,
    }[sort_by]
    stmt = stmt.order_by(sort_col.asc().nullslast() if sort_dir == "asc" else sort_col.desc().nullslast())

    rows = (await session.execute(stmt)).all()
    return CustomerListResponse(
        items=[
            CustomerListItem(
                id=r.id,
                tenant_id=r.tenant_id,
                phone_e164=r.phone_e164,
                name=r.name,
                score=r.score or 0,
                created_at=r.created_at,
                conversation_count=r.conversation_count,
                effective_stage=r.effective_stage,
                last_activity_at=r.last_activity_at,
                assigned_user_email=r.assigned_user_email,
            )
            for r in rows
        ]
    )


@router.get("/{customer_id:uuid}", response_model=CustomerDetail)
async def get_customer(
    customer_id: UUID,
    user: AuthUser = Depends(current_user),
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
        email=cust.email,
        score=cust.score,
        attrs=cust.attrs or {},
        created_at=cust.created_at,
        conversations=conversations,
        last_extracted_data=last_extracted,
        total_cost_usd=total_cost,
    )


@router.patch("/{customer_id:uuid}", response_model=CustomerDetail)
async def patch_customer(
    customer_id: UUID,
    body: CustomerPatch,
    user: AuthUser = Depends(current_user),
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


@router.patch("/{customer_id:uuid}/score", response_model=CustomerDetail)
async def patch_customer_score(
    customer_id: UUID,
    body: ScorePatch,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerDetail:
    result = await session.execute(
        update(Customer)
        .where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
        .values(score=body.score)
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "customer not found")
    await session.commit()
    return await get_customer(customer_id, user, tenant_id, session)


CUSTOMER_IMPORT_MAX_ROWS: int = 2000
CUSTOMER_IMPORT_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB raw CSV cap.


def _read_csv_rows(raw: bytes) -> list[dict[str, str]]:
    """Common decode + parse for import + preview. Strips UTF-8 BOM."""
    text_data = raw.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text_data))
    rows = list(reader)
    if len(rows) > CUSTOMER_IMPORT_MAX_ROWS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"too many rows (max {CUSTOMER_IMPORT_MAX_ROWS})",
        )
    return rows


def _parse_import_row(
    idx: int,
    row: dict[str, str],
    seen_phones: set[str],
) -> tuple[dict | None, str | None]:
    """Validate one CSV row. Returns (parsed, error). Either (None, str) on
    error or ({phone, name, email, score}, None) on success.

    Accepts header aliases (``phone``/``phone_e164``/``telefono``,
    ``name``/``nombre``, ``email``/``correo``, ``score``/``puntaje``) so
    operators can paste from common spreadsheet templates without renaming.
    """
    phone = _normalize_phone(
        row.get("phone")
        or row.get("phone_e164")
        or row.get("telefono")
        or ""
    )
    if not phone:
        return None, f"row {idx}: invalid phone"
    if phone in seen_phones:
        return None, f"row {idx}: duplicate phone in file"

    name = (row.get("name") or row.get("nombre") or "").strip() or None

    email_raw = row.get("email") or row.get("correo")
    email, email_err = _validate_email(email_raw)
    if email_err:
        return None, f"row {idx}: {email_err}"

    score_raw = row.get("score") or row.get("puntaje")
    score, score_err = _validate_score(score_raw)
    if score_err:
        return None, f"row {idx}: {score_err}"

    return {
        "phone": phone,
        "name": name,
        "email": email,
        "score": score,
    }, None


class CustomerImportPreviewRow(BaseModel):
    row: int
    phone: str
    name: str | None
    email: str | None
    score: int | None
    will: str  # "create" | "update"


class CustomerImportPreview(BaseModel):
    valid_rows: list[CustomerImportPreviewRow]
    errors: list[str]
    total: int


@router.post("/import/preview", response_model=CustomerImportPreview)
async def preview_import(
    file: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerImportPreview:
    """Validate without committing. The UI shows the operator exactly what
    will create vs update before they confirm. Same parsing and validation
    rules as :func:`import_customers`."""
    raw = await file.read()
    if len(raw) > CUSTOMER_IMPORT_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file too large (max {CUSTOMER_IMPORT_MAX_BYTES // 1024 // 1024} MB)",
        )
    rows = _read_csv_rows(raw)
    valid: list[CustomerImportPreviewRow] = []
    errors: list[str] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        parsed, err = _parse_import_row(idx, row, seen)
        if err:
            errors.append(err)
            continue
        assert parsed is not None
        seen.add(parsed["phone"])
        existing = (
            await session.execute(
                select(Customer.id).where(
                    Customer.tenant_id == tenant_id,
                    Customer.phone_e164 == parsed["phone"],
                )
            )
        ).scalar_one_or_none()
        valid.append(
            CustomerImportPreviewRow(
                row=idx,
                phone=parsed["phone"],
                name=parsed["name"],
                email=parsed["email"],
                score=parsed["score"],
                will="update" if existing else "create",
            )
        )
    return CustomerImportPreview(valid_rows=valid, errors=errors, total=len(rows))


@router.post("/import", response_model=CustomerImportResult)
async def import_customers(
    file: UploadFile = File(...),
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> CustomerImportResult:
    raw = await file.read()
    if len(raw) > CUSTOMER_IMPORT_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file too large (max {CUSTOMER_IMPORT_MAX_BYTES // 1024 // 1024} MB)",
        )
    rows = _read_csv_rows(raw)
    created = 0
    updated = 0
    errors: list[str] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        parsed, err = _parse_import_row(idx, row, seen)
        if err:
            errors.append(err)
            continue
        assert parsed is not None
        seen.add(parsed["phone"])
        existing = (
            await session.execute(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.phone_e164 == parsed["phone"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            if parsed["name"]:
                existing.name = parsed["name"]
            if parsed["email"]:
                existing.email = parsed["email"]
            if parsed["score"] is not None:
                existing.score = parsed["score"]
            updated += 1
        else:
            session.add(
                Customer(
                    tenant_id=tenant_id,
                    phone_e164=parsed["phone"],
                    name=parsed["name"],
                    email=parsed["email"],
                    score=parsed["score"] or 0,
                )
            )
            created += 1
    await session.commit()
    return CustomerImportResult(created=created, updated=updated, errors=errors)


@router.get("/export")
async def export_customers(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """CSV export, lateral-joined with the latest conversation for
    ``effective_stage`` + ``last_activity_at``. Formula-leading values are
    prefixed with ``'`` so a recipient opening the file in Excel/Sheets
    doesn't trigger formula execution."""
    latest_conv_sq = (
        select(
            Conversation.customer_id.label("cid"),
            Conversation.current_stage.label("effective_stage"),
            Conversation.last_activity_at.label("last_activity_at"),
            func.row_number()
            .over(
                partition_by=Conversation.customer_id,
                order_by=Conversation.last_activity_at.desc(),
            )
            .label("rn"),
        )
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.deleted_at.is_(None),
        )
        .subquery()
    )
    latest_conv = (
        select(
            latest_conv_sq.c.cid,
            latest_conv_sq.c.effective_stage,
            latest_conv_sq.c.last_activity_at,
        )
        .where(latest_conv_sq.c.rn == 1)
        .subquery()
    )

    stmt = (
        select(
            Customer.id,
            Customer.phone_e164,
            Customer.name,
            Customer.email,
            Customer.score,
            latest_conv.c.effective_stage,
            latest_conv.c.last_activity_at,
        )
        .select_from(Customer)
        .outerjoin(latest_conv, latest_conv.c.cid == Customer.id)
        .where(Customer.tenant_id == tenant_id)
        .order_by(Customer.created_at.desc())
        .limit(5000)
    )
    rows = (await session.execute(stmt)).all()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["name", "phone", "email", "effective_stage", "score", "last_activity"])
    for row in rows:
        writer.writerow(
            [
                _csv_safe(row.name or ""),
                _csv_safe(row.phone_e164),
                _csv_safe(row.email or ""),
                _csv_safe(row.effective_stage or ""),
                row.score or 0,
                row.last_activity_at.isoformat() if row.last_activity_at else "",
            ]
        )
    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="customers.csv"'},
    )


def _normalize_phone(raw: str) -> str | None:
    """Canonical E.164 used for the unique key ``(tenant_id, phone_e164)``.

    Mexican mobile numbers historically carried a leading ``1`` after the
    country code (``+521…``) that newer Meta APIs strip. Both shapes refer
    to the same physical phone, so we collapse them to ``+52…``. Without
    this, an import sees ``+5215512345678`` and ``+525512345678`` as two
    different customers.

    The presence of a leading ``+`` in the original input matters: with a
    ``+``, the digits are an explicit E.164 country code and we don't
    second-guess them (so ``+14155551234`` stays a US number). Without the
    ``+``, an 11-digit number starting with ``1`` is interpreted as the
    Mexican legacy mobile shape (``15512345678`` → ``+525512345678``),
    matching how operators paste numbers in this product.
    """
    if not raw:
        return None
    has_plus = "+" in raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None

    if has_plus:
        # E.164 explicitly stated; only canonicalise the MX legacy ``1``.
        if len(digits) == 13 and digits.startswith("521"):
            return f"+52{digits[3:]}"
        if 11 <= len(digits) <= 15:
            return f"+{digits}"
        return None

    # No ``+``. Operator typed bare digits — apply the MX heuristics.
    # 10 digits = MX local.
    if len(digits) == 10:
        return f"+52{digits}"
    # 11 digits starting with ``1`` = MX legacy mobile without country code.
    if len(digits) == 11 and digits.startswith("1"):
        return f"+52{digits[1:]}"
    # 12 digits starting with ``52`` = MX with country code, no legacy 1.
    if len(digits) == 12 and digits.startswith("52"):
        return f"+{digits}"
    # 13 digits starting with ``521`` = MX with country code AND legacy 1.
    if len(digits) == 13 and digits.startswith("521"):
        return f"+52{digits[3:]}"
    # Anything else 11–15 digits: assume E.164 sans ``+``.
    if 11 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def _csv_safe(value: str) -> str:
    """Prefix dangerous formula-leading chars with `'` so a recipient
    opening the CSV in Excel/Sheets doesn't trigger formula execution.

    Covered prefixes: ``=`` (formula), ``+`` ``-`` (formula in some locales),
    ``@`` (@SUM macro shortcut), and the tab/CR characters Excel treats as
    cell separators when pasted.
    """
    if not value:
        return value
    first = value[0]
    if first in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _validate_score(raw: object) -> tuple[int | None, str | None]:
    """Returns (score, err). score=None and err=None means "blank, leave default"."""
    if raw is None or raw == "":
        return None, None
    try:
        n = int(str(raw).strip())
    except (ValueError, TypeError):
        return None, "score must be an integer 0-100"
    if n < 0 or n > 100:
        return None, "score must be between 0 and 100"
    return n, None


def _validate_email(raw: object) -> tuple[str | None, str | None]:
    """Lightweight email validation. Empty -> None. Returns (email, err)."""
    if raw is None or raw == "":
        return None, None
    cleaned = str(raw).strip()
    if not cleaned:
        return None, None
    if "@" not in cleaned or len(cleaned) > 160:
        return None, "email looks invalid"
    return cleaned, None

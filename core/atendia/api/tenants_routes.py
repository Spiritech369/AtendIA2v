"""Operator dashboard — tenant configuration (Phase 4 Block E, T28-T30).

Three pairs of endpoints, all tenant-scoped via `current_tenant_id`:

* `GET /api/v1/tenants/:tid/pipeline` → active pipeline definition.
* `PUT /api/v1/tenants/:tid/pipeline` → creates a NEW version row
  (don't UPDATE — preserve history), marks it active, deactivates
  prior versions.
* `GET/PUT /api/v1/tenants/:tid/brand-facts` → JSONB sub-key
  `default_messages.brand_facts` on tenant_branding.
* `GET/PUT /api/v1/tenants/:tid/tone` → tenant_branding.voice.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.tenant import Tenant
from atendia.db.models.tenant_config import TenantBranding, TenantPipeline
from atendia.db.session import get_db_session

router = APIRouter()


# ---------- Pipeline ----------


class PipelineResponse(BaseModel):
    version: int
    definition: dict
    active: bool
    created_at: datetime


class PipelinePutBody(BaseModel):
    definition: dict = Field(..., description="The full pipeline JSONB.")


@router.get("/pipeline", response_model=PipelineResponse)
async def get_pipeline(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> PipelineResponse:
    row = (
        await session.execute(
            select(TenantPipeline)
            .where(
                TenantPipeline.tenant_id == tenant_id,
                TenantPipeline.active.is_(True),
            )
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active pipeline")
    return PipelineResponse(
        version=row.version,
        definition=row.definition,
        active=row.active,
        created_at=row.created_at,
    )


@router.put("/pipeline", response_model=PipelineResponse)
async def put_pipeline(
    body: PipelinePutBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> PipelineResponse:
    # Find the current max version (there might be 0 rows on first save).
    max_version = (
        await session.execute(
            select(TenantPipeline.version)
            .where(TenantPipeline.tenant_id == tenant_id)
            .order_by(TenantPipeline.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    new_version = (max_version or 0) + 1

    # Deactivate all prior versions, then insert + activate the new one.
    await session.execute(
        update(TenantPipeline)
        .where(TenantPipeline.tenant_id == tenant_id)
        .values(active=False)
    )
    new_row = TenantPipeline(
        tenant_id=tenant_id,
        version=new_version,
        definition=body.definition,
        active=True,
    )
    session.add(new_row)
    await session.commit()
    await session.refresh(new_row)
    return PipelineResponse(
        version=new_row.version,
        definition=new_row.definition,
        active=new_row.active,
        created_at=new_row.created_at,
    )


# ---------- Branding (brand_facts + tone) ----------


class BrandFactsResponse(BaseModel):
    brand_facts: dict


class BrandFactsPutBody(BaseModel):
    brand_facts: dict


class ToneResponse(BaseModel):
    voice: dict


class TonePutBody(BaseModel):
    voice: dict


class TimezoneResponse(BaseModel):
    timezone: str


class TimezonePutBody(BaseModel):
    timezone: str = Field(min_length=1, max_length=40)


async def _ensure_branding(
    session: AsyncSession, tenant_id: UUID
) -> TenantBranding:
    """Fetch the branding row, creating an empty one if missing.
    Idempotent — safe to call from both GET and PUT."""
    row = (
        await session.execute(
            select(TenantBranding).where(TenantBranding.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = TenantBranding(tenant_id=tenant_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/brand-facts", response_model=BrandFactsResponse)
async def get_brand_facts(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BrandFactsResponse:
    row = await _ensure_branding(session, tenant_id)
    facts = (row.default_messages or {}).get("brand_facts", {})
    return BrandFactsResponse(brand_facts=facts)


@router.put("/brand-facts", response_model=BrandFactsResponse)
async def put_brand_facts(
    body: BrandFactsPutBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> BrandFactsResponse:
    row = await _ensure_branding(session, tenant_id)
    new_messages = dict(row.default_messages or {})
    new_messages["brand_facts"] = body.brand_facts
    await session.execute(
        update(TenantBranding)
        .where(TenantBranding.tenant_id == tenant_id)
        .values(default_messages=new_messages)
    )
    await session.commit()
    return BrandFactsResponse(brand_facts=body.brand_facts)


@router.get("/tone", response_model=ToneResponse)
async def get_tone(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ToneResponse:
    row = await _ensure_branding(session, tenant_id)
    return ToneResponse(voice=row.voice or {})


@router.put("/tone", response_model=ToneResponse)
async def put_tone(
    body: TonePutBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ToneResponse:
    await _ensure_branding(session, tenant_id)
    await session.execute(
        update(TenantBranding)
        .where(TenantBranding.tenant_id == tenant_id)
        .values(voice=body.voice)
    )
    await session.commit()
    return ToneResponse(voice=body.voice)


@router.get("/timezone", response_model=TimezoneResponse)
async def get_timezone(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TimezoneResponse:
    timezone = (
        await session.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))
    ).scalar_one()
    return TimezoneResponse(timezone=timezone)


@router.put("/timezone", response_model=TimezoneResponse)
async def put_timezone(
    body: TimezonePutBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TimezoneResponse:
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid timezone") from exc
    await session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(timezone=body.timezone)
    )
    await session.commit()
    return TimezoneResponse(timezone=body.timezone)


# ---------- Inbox Config ----------

DEFAULT_INBOX_CONFIG: dict = {
    "layout": {
        "three_pane": True,
        "rail_width": "expanded",
        "list_max_width": 360,
        "composer_density": "comfortable",
        "sticky_composer": True,
    },
    "filter_chips": [
        {"id": "unread",            "label": "Sin leer",             "color": "#4f72f5", "query": "read_at IS NULL",                             "live_count": True,  "visible": True, "order": 0},
        {"id": "mine",              "label": "Mías",                 "color": "#9b72f5", "query": "assigned_to = current_user",                  "live_count": True,  "visible": True, "order": 1},
        {"id": "unassigned",        "label": "Sin asignar",          "color": "#f5a623", "query": "assigned_to IS NULL AND status != 'closed'",  "live_count": False, "visible": True, "order": 2},
        {"id": "awaiting_customer", "label": "En espera de cliente", "color": "#4fa8f5", "query": "stage = 'waiting_customer'",                  "live_count": True,  "visible": True, "order": 3},
        {"id": "stale",             "label": "Inactivas >24h",       "color": "#f25252", "query": "last_message_at < now() - interval '24h'",   "live_count": True,  "visible": True, "order": 4},
    ],
    "stage_rings": [
        {"stage_id": "nuevo",      "emoji": "🆕", "color": "#6b7cf5", "sla_hours": 24},
        {"stage_id": "en_curso",   "emoji": "🔄", "color": "#10c98f", "sla_hours": 4},
        {"stage_id": "en_espera",  "emoji": "⏳", "color": "#f5a623", "sla_hours": 48},
        {"stage_id": "cotizacion", "emoji": "💰", "color": "#9b72f5", "sla_hours": 12},
        {"stage_id": "documentos", "emoji": "📄", "color": "#4fa8f5", "sla_hours": 24},
        {"stage_id": "cierre",     "emoji": "🏁", "color": "#10c98f", "sla_hours": None},
    ],
    "handoff_rules": [
        {"id": "ask_price", "intent": "ASK_PRICE",       "confidence": 82,  "action": "suggest_template",        "template": "precio_hr_v_2025",  "enabled": True,  "order": 0},
        {"id": "docs_miss", "intent": "DOCS_MISSING",    "confidence": 75,  "action": "send_checklist",          "template": "docs_checklist_v2", "enabled": True,  "order": 1},
        {"id": "human_req", "intent": "HUMAN_REQUESTED", "confidence": 90,  "action": "assign_to_free_operator", "template": "",                  "enabled": True,  "order": 2},
        {"id": "stale_24h", "intent": "STALE_24H",       "confidence": 100, "action": "trigger_followup",        "template": "followup_24h",      "enabled": False, "order": 3},
    ],
}


class InboxConfigBody(BaseModel):
    inbox_config: dict = Field(..., description="Full inbox config object.")


class InboxConfigResponse(BaseModel):
    inbox_config: dict


def _normalize_inbox_config(config: object) -> dict:
    if not isinstance(config, dict):
        return deepcopy(DEFAULT_INBOX_CONFIG)

    normalized = deepcopy(DEFAULT_INBOX_CONFIG)

    layout = config.get("layout")
    if isinstance(layout, dict):
        normalized["layout"].update(
            {key: value for key, value in layout.items() if key in normalized["layout"]}
        )

    for key in ("filter_chips", "stage_rings", "handoff_rules"):
        value = config.get(key)
        if isinstance(value, list):
            normalized[key] = value

    for key, value in config.items():
        if key not in normalized:
            normalized[key] = value

    return normalized


@router.get("/inbox-config", response_model=InboxConfigResponse)
async def get_inbox_config(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> InboxConfigResponse:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    cfg = _normalize_inbox_config((tenant.config or {}).get("inbox_config"))
    return InboxConfigResponse(inbox_config=cfg)


@router.put("/inbox-config", response_model=InboxConfigResponse)
async def put_inbox_config(
    body: InboxConfigBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> InboxConfigResponse:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    inbox_config = _normalize_inbox_config(body.inbox_config)
    new_config = dict(tenant.config or {})
    new_config["inbox_config"] = inbox_config
    await session.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(config=new_config)
    )
    await session.commit()
    return InboxConfigResponse(inbox_config=inbox_config)


# Suppress unused-import warning when we don't actually use UTC anywhere
# above (we kept the import for future timestamp work).
_ = UTC

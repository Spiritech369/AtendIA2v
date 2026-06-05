from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_user
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session

router = APIRouter()
tenant_capabilities_router = APIRouter()

SchemaVersion = Literal["2026-05-31.p0"]

SCHEMA_VERSION: SchemaVersion = "2026-05-31.p0"

ROLES_AVAILABLE = ["operator", "tenant_admin", "superadmin"]
PIPELINE_MODES_AVAILABLE = ["manual", "assist", "auto"]
ACTIONS_AVAILABLE = [
    "send_message",
    "assign_human",
    "create_handoff",
    "create_appointment",
    "update_customer_field",
]
RULE_OPERATORS_AVAILABLE = [
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "greater_than",
    "less_than",
    "exists",
    "missing",
]
HANDOFF_REASONS_AVAILABLE = [
    "customer_requested_human",
    "low_ai_confidence",
    "documents_incomplete",
    "pricing_negotiation",
    "payment_or_system_error",
    "knowledge_gap",
]

BASE_ROUTE_CAPABILITIES = {
    "route.dashboard",
    "route.conversations",
    "route.handoffs",
    "route.customers",
    "route.appointments",
    "route.knowledge",
    "route.turn_traces",
    "route.workflows",
    "route.analytics",
    "route.exports",
}

TENANT_ADMIN_CAPABILITIES = {
    "route.agents",
    "route.composer",
    "route.customer_fields",
    "route.pipeline",
    "route.expediente",
    "route.config_linter",
    "route.inbox_settings",
    "route.catalog",
    "route.users",
    "route.config",
    "agents.manage",
    "composer.manage",
    "customer_fields.manage",
    "pipeline.write",
    "inbox_config.write",
    "tenant_config.write",
    "users.manage",
    "workflows.publish",
    "agents.publish",
}

SUPERADMIN_CAPABILITIES = {
    "route.audit_log",
    "audit.read",
}


class FeatureFlags(BaseModel):
    show_nyi_controls: bool = False
    demo_mode: bool = False
    mock_knowledge_model: bool = False


class Limits(BaseModel):
    max_pipeline_stages: int = 30
    max_workflow_nodes: int = 100


class CurrentUserCapabilities(BaseModel):
    id: UUID
    role: str
    capabilities: list[str]


class ProductConfigSchema(BaseModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    roles_available: list[str]
    pipeline_modes_available: list[str]
    actions_available: list[str]
    rule_operators_available: list[str]
    handoff_reasons_available: list[str]
    feature_flags: FeatureFlags = FeatureFlags()
    limits: Limits = Limits()


class TenantCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schema_version: SchemaVersion = SCHEMA_VERSION
    tenant_id: UUID
    feature_flags: FeatureFlags
    limits: Limits = Limits()
    current_user: CurrentUserCapabilities


def capabilities_for_role(role: str) -> list[str]:
    caps = set(BASE_ROUTE_CAPABILITIES)
    if role in {"tenant_admin", "superadmin"}:
        caps.update(TENANT_ADMIN_CAPABILITIES)
    if role == "superadmin":
        caps.update(SUPERADMIN_CAPABILITIES)
    return sorted(caps)


@router.get("/schema", response_model=ProductConfigSchema)
async def get_product_config_schema(
    _user: AuthUser = Depends(current_user),
) -> ProductConfigSchema:
    """Expose the minimal shared product schema before tenant-editable config.

    These lists are deliberately versioned capabilities, not tenant config.
    Frontend can render safely without inventing enums that drift from backend.
    """
    return ProductConfigSchema(
        roles_available=ROLES_AVAILABLE,
        pipeline_modes_available=PIPELINE_MODES_AVAILABLE,
        actions_available=ACTIONS_AVAILABLE,
        rule_operators_available=RULE_OPERATORS_AVAILABLE,
        handoff_reasons_available=HANDOFF_REASONS_AVAILABLE,
    )


@tenant_capabilities_router.get("/{tenant_id}/capabilities", response_model=TenantCapabilitiesResponse)
async def get_tenant_capabilities(
    tenant_id: UUID,
    user: AuthUser = Depends(current_user),
    session: AsyncSession = Depends(get_db_session),
) -> TenantCapabilitiesResponse:
    if user.role != "superadmin" and user.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant access denied")

    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")

    demo_mode = bool(tenant.is_demo)
    return TenantCapabilitiesResponse(
        tenant_id=tenant.id,
        feature_flags=FeatureFlags(
            show_nyi_controls=False,
            demo_mode=demo_mode,
            mock_knowledge_model=demo_mode,
        ),
        current_user=CurrentUserCapabilities(
            id=user.user_id,
            role=user.role,
            capabilities=capabilities_for_role(user.role),
        ),
    )

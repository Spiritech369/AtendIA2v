from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.pilot_policy import AgentRuntimeV2PilotPolicyService
from atendia.agent_runtime.shadow_analytics import (
    AgentRuntimeV2ShadowAnalyticsService,
    ShadowReportFilters,
)
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, require_tenant_admin
from atendia.db.session import get_db_session

router = APIRouter()


@router.get("/pilot-report")
async def get_agent_runtime_v2_pilot_report(
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    del user
    return await AgentRuntimeV2PilotPolicyService(session).build_report(tenant_id=tenant_id)


@router.get("/shadow-report")
async def get_agent_runtime_v2_shadow_report(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    conversation_id: UUID | None = Query(default=None),
    channel: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    include_examples: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=200),
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    del user
    filters = ShadowReportFilters(
        date_from=date_from,
        date_to=date_to,
        agent_id=agent_id,
        conversation_id=conversation_id,
        channel=channel,
        min_confidence=min_confidence,
        include_examples=include_examples,
        limit=limit,
    )
    return await AgentRuntimeV2ShadowAnalyticsService(session).build_report(
        tenant_id=tenant_id,
        filters=filters,
    )

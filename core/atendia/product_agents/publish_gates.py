"""Publish Control gates for Respond-Style Product Agent deployments.

A deployment that opts into the Respond-Style direct route
(``metadata_json.respond_style_enabled``) cannot get an approvable publish
request unless:

1. the Customer Copy Kill Map hard block holds (import-graph audit clean),
2. the latest Respond-Style direct Test Lab run for the version passed.

Deployments without the opt-in flag are unaffected — these gates add
blockers, never remove existing ones, and never send anything.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.respond_style_route_audit import audit_direct_route_imports
from atendia.db.models.product_agent import AgentDeployment, AgentTestRun

logger = logging.getLogger(__name__)

DIRECT_EXECUTION_MODE = "respond_style_product_agent_direct"
DIRECT_DECISION_READY = "RESPOND_STYLE_DIRECT_NO_SEND_READY"


async def respond_style_publish_blockers(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
    deployment: AgentDeployment,
) -> list[dict[str, Any]]:
    metadata = dict(deployment.metadata_json or {})
    if not metadata.get("respond_style_enabled", False):
        return []

    blockers: list[dict[str, Any]] = []

    try:
        violations = audit_direct_route_imports()
    except Exception as exc:  # audit must fail closed, never silently pass
        blockers.append(
            {
                "code": "respond_style_hard_block_audit_failed",
                "detail": type(exc).__name__,
            }
        )
    else:
        if violations:
            blockers.append(
                {
                    "code": "respond_style_hard_block_battery_failed",
                    "violations": violations,
                }
            )

    latest_direct_run = await _latest_direct_test_run(
        session, tenant_id=tenant_id, version_id=version_id
    )
    if latest_direct_run is None:
        blockers.append({"code": "respond_style_test_lab_direct_missing"})
    elif latest_direct_run.decision != DIRECT_DECISION_READY:
        blockers.append(
            {
                "code": "respond_style_test_lab_direct_not_passed",
                "decision": latest_direct_run.decision,
                "status": latest_direct_run.status,
            }
        )
    return blockers


async def _latest_direct_test_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version_id: UUID,
) -> AgentTestRun | None:
    result = await session.execute(
        select(AgentTestRun)
        .where(
            AgentTestRun.tenant_id == tenant_id,
            AgentTestRun.agent_version_id == version_id,
        )
        .order_by(AgentTestRun.created_at.desc())
    )
    for run in result.scalars():
        coverage = dict(run.coverage_summary or {})
        if coverage.get("execution_mode") == DIRECT_EXECUTION_MODE:
            return run
    return None


__all__ = ["respond_style_publish_blockers"]

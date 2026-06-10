"""Log-only preview of Respond-Style routing for inbound messages.

Phase 12B: this module only OBSERVES. It resolves what route each Product
Agent deployment of the tenant WOULD take (direct vs legacy) and returns
structured previews for logging/trace. It never routes, never sends, never
mutates state, and any failure is swallowed by the caller — the inbound
pipeline must be completely unaffected.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime import DeploymentView, RespondStyleDeploymentResolver
from atendia.db.models.product_agent import AgentDeployment

logger = logging.getLogger(__name__)

_resolver = RespondStyleDeploymentResolver()


async def preview_respond_style_routing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    """Returns preview resolutions for the tenant's deployments (log-only)."""
    result = await session.execute(
        select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
    )
    deployments = list(result.scalars())
    previews: list[dict[str, Any]] = []
    for deployment in deployments:
        metadata = dict(deployment.metadata_json or {})
        view = DeploymentView(
            tenant_id=str(deployment.tenant_id),
            deployment_id=str(deployment.id),
            agent_id=str(deployment.agent_id),
            active_version_id=(
                str(deployment.active_version_id)
                if deployment.active_version_id
                else None
            ),
            channel=deployment.channel,
            environment=deployment.environment,
            publish_state=deployment.publish_state,
            runtime_mode=deployment.runtime_mode,
            respond_style_enabled=bool(metadata.get("respond_style_enabled", False)),
            send_enabled=bool(deployment.send_enabled),
            outbox_enabled=bool(deployment.outbox_enabled),
            live_send_enabled=bool(deployment.live_send_enabled),
            metadata=metadata,
        )
        previews.append(_resolver.resolve(view).model_dump(mode="json"))
    return previews


async def log_routing_preview_safely(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID | str | None = None,
) -> None:
    """Best-effort preview logging. Swallows every exception by design."""
    try:
        previews = await preview_respond_style_routing(session, tenant_id=tenant_id)
        if previews:
            logger.info(
                "respond_style_routing_preview tenant=%s conversation=%s previews=%s",
                tenant_id,
                conversation_id,
                previews,
            )
    except Exception:  # pragma: no cover - observation must never break inbound
        logger.debug(
            "respond_style_routing_preview_failed tenant=%s", tenant_id, exc_info=True
        )


__all__ = ["log_routing_preview_safely", "preview_respond_style_routing"]

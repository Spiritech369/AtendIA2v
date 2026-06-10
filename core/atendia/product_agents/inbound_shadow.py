"""Opt-in inbound shadow over the Respond-Style direct route (Phase 13B).

For deployments that explicitly opt in
(``metadata_json.respond_style_inbound_shadow_enabled``), each inbound
message ALSO runs through ProductAgentRuntime in no-send mode and the
resulting evidence is logged. Observation only: nothing is delivered or
persisted to customer-facing state, the legacy pipeline is untouched, and
every failure is swallowed by the caller-facing wrapper.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime import (
    ConversationStateSnapshot,
    ProductAgentPublishedConfig,
    TranscriptMessage,
)
from atendia.config import get_settings
from atendia.db.models.message import MessageRow
from atendia.db.models.product_agent import AgentDeployment
from atendia.product_agents.routing_preview import preview_respond_style_routing

logger = logging.getLogger(__name__)

SHADOW_FLAG = "respond_style_inbound_shadow_enabled"
TRANSCRIPT_LIMIT = 12


class _StaticSources:
    def __init__(
        self,
        config: ProductAgentPublishedConfig,
        state: ConversationStateSnapshot,
    ) -> None:
        self._config = config
        self._state = state

    def load_config(self, runtime_input):
        return self._config

    def load_state(self, runtime_input):
        return self._state


async def run_inbound_shadow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: Any,
    inbound_text: str,
) -> list[dict[str, Any]]:
    """Runs the direct route in shadow for opted-in deployments and returns
    evidence summaries. Raises on internal errors; use the safe wrapper from
    the inbound pipeline."""
    api_key = get_settings().openai_api_key
    if not api_key:
        return []

    opted_in = await _opted_in_deployments(session, tenant_id=tenant_id)
    if not opted_in:
        return []

    previews = {
        item["deployment_id"]: item
        for item in await preview_respond_style_routing(session, tenant_id=tenant_id)
    }
    summaries: list[dict[str, Any]] = []
    for deployment in opted_in:
        preview = previews.get(str(deployment.id))
        if preview is None or preview["route_preview"] != "product_agent_direct":
            continue
        # Phase 16: the shadow turn runs through the REAL AgentService so it
        # exercises the same publish gates, shadow field memory and
        # no_send_followup policy as the future live route. The bridge
        # resolves the deployment itself; legacy never runs because the
        # preview above guarantees a direct-route deployment exists.
        from atendia.agent_runtime.agent_service import AgentService

        service = AgentService(session=session)
        outcome = await service.handle_turn(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            inbound_text=inbound_text,
            turn_number=0,
            mode="no_send",
            metadata={"channel": deployment.channel, "inbound_shadow": True},
        )
        trace = (
            (outcome.output.trace_metadata or {}).get("respond_style_agent_service")
            if outcome.output is not None
            else None
        ) or {}
        summaries.append(
            {
                "deployment_id": trace.get("deployment_id") or str(deployment.id),
                "agent_version_id": trace.get("agent_version_id"),
                "route": trace.get("route"),
                "legacy_path_used": trace.get("legacy_path_used"),
                "send_decision": trace.get("send_decision", "no_send"),
                "send_allowed": outcome.send.send_decision.allowed,
                "outbox_write_attempted": outcome.send.outbox_write_attempted,
                "blocked_reason": trace.get("blocked_reason"),
                "final_message_candidate": trace.get("final_message_candidate"),
                "tools": [
                    {"tool_name": item.get("tool_name"), "status": item.get("status")}
                    for item in trace.get("tool_results") or []
                ],
                "field_state": trace.get("field_state"),
                "field_update_proposals": trace.get("field_update_proposals"),
                "handoff_proposal": trace.get("handoff_proposal"),
                "no_send_followup": trace.get("no_send_followup"),
                "validator": trace.get("validator"),
                "side_effects": trace.get("side_effects"),
            }
        )
    return summaries


async def run_inbound_shadow_safely(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: Any,
    inbound_text: str,
) -> None:
    """Best-effort shadow execution. Swallows every exception by design."""
    try:
        summaries = await run_inbound_shadow(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
        )
        if summaries:
            logger.info(
                "respond_style_inbound_shadow tenant=%s conversation=%s results=%s",
                tenant_id,
                conversation_id,
                summaries,
            )
    except Exception:  # pragma: no cover - observation must never break inbound
        logger.debug(
            "respond_style_inbound_shadow_failed tenant=%s", tenant_id, exc_info=True
        )


async def _opted_in_deployments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[AgentDeployment]:
    result = await session.execute(
        select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
    )
    return [
        deployment
        for deployment in result.scalars()
        if dict(deployment.metadata_json or {}).get(SHADOW_FLAG, False)
    ]


async def _recent_transcript(
    session: AsyncSession,
    *,
    conversation_id: Any,
) -> list[TranscriptMessage]:
    result = await session.execute(
        select(MessageRow)
        .where(MessageRow.conversation_id == conversation_id)
        .order_by(MessageRow.created_at.desc())
        .limit(TRANSCRIPT_LIMIT)
    )
    rows = list(result.scalars())
    rows.reverse()
    transcript: list[TranscriptMessage] = []
    for row in rows:
        role = "customer" if row.direction == "inbound" else (
            "assistant" if row.direction == "outbound" else "system_internal"
        )
        transcript.append(
            TranscriptMessage(
                role=role,
                text=row.text,
                message_id=str(row.id),
                timestamp=str(row.created_at),
            )
        )
    return transcript


__all__ = ["run_inbound_shadow", "run_inbound_shadow_safely"]

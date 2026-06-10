"""Opt-in inbound shadow over the Respond-Style direct route (Phase 13B).

For deployments that explicitly opt in
(``metadata_json.respond_style_inbound_shadow_enabled``), each inbound
message ALSO runs through ProductAgentRuntime in no-send mode and the
resulting evidence is logged. Observation only: nothing is delivered or
persisted to customer-facing state, the legacy pipeline is untouched, and
every failure is swallowed by the caller-facing wrapper.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime import (
    ConversationStateSnapshot,
    ProductAgentPublishedConfig,
    TranscriptMessage,
)
from atendia.config import get_settings
from atendia.db.models.message import MessageRow
from atendia.db.models.product_agent import AgentDeployment
from atendia.db.models.turn_trace import TurnTrace
from atendia.product_agents.routing_preview import preview_respond_style_routing

logger = logging.getLogger(__name__)

SHADOW_FLAG = "respond_style_inbound_shadow_enabled"
SHADOW_ALLOWED_PHONES_KEY = "respond_style_inbound_shadow_allowed_phones"
SHADOW_ROUTER_TRIGGER = "respond_style_inbound_shadow_auto"
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
    inbound_message_id: Any | None = None,
    from_phone_e164: str | None = None,
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
    opted_in = [
        deployment
        for deployment in opted_in
        if _deployment_allows_phone(deployment, from_phone_e164)
    ]
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
        if inbound_message_id is not None and await _existing_shadow_trace(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        ):
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
            metadata={
                "channel": deployment.channel,
                "inbound_shadow": True,
                "inbound_message_id": str(inbound_message_id)
                if inbound_message_id is not None
                else None,
                "from_phone_e164": from_phone_e164,
            },
        )
        trace = (
            (outcome.output.trace_metadata or {}).get("respond_style_agent_service")
            if outcome.output is not None
            else None
        ) or {}
        summary = _summary_from_outcome(
            trace=trace,
            deployment=deployment,
            outcome=outcome,
        )
        if inbound_message_id is not None:
            trace_id = await _record_shadow_trace(
                session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=inbound_text,
                inbound_message_id=inbound_message_id,
                from_phone_e164=from_phone_e164,
                deployment=deployment,
                summary=summary,
            )
            summary["turn_trace_id"] = str(trace_id)
        summaries.append(summary)
    return summaries


async def run_inbound_shadow_safely(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: Any,
    inbound_text: str,
    inbound_message_id: Any | None = None,
    from_phone_e164: str | None = None,
) -> None:
    """Best-effort shadow execution. Swallows every exception by design."""
    try:
        summaries = await run_inbound_shadow(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
            inbound_message_id=inbound_message_id,
            from_phone_e164=from_phone_e164,
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


def _summary_from_outcome(
    *,
    trace: dict[str, Any],
    deployment: AgentDeployment,
    outcome: Any,
) -> dict[str, Any]:
    return {
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


def _deployment_allows_phone(
    deployment: AgentDeployment,
    from_phone_e164: str | None,
) -> bool:
    metadata = dict(deployment.metadata_json or {})
    allowed = metadata.get(SHADOW_ALLOWED_PHONES_KEY)
    if not allowed:
        return True
    if from_phone_e164 is None:
        return False
    if not isinstance(allowed, list):
        return False
    actual = _phone_variants(from_phone_e164)
    allowed_variants: set[str] = set()
    for item in allowed:
        allowed_variants.update(_phone_variants(str(item)))
    return bool(actual & allowed_variants)


def _phone_variants(value: str) -> set[str]:
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return set()
    variants = {digits}
    if len(digits) >= 10:
        variants.add(digits[-10:])
    # Mexico mobile numbers can appear as +52 1 NNN... or +52 NNN...
    if digits.startswith("521") and len(digits) == 13:
        variants.add("52" + digits[3:])
    elif digits.startswith("52") and len(digits) == 12:
        variants.add("521" + digits[2:])
    return variants


async def _existing_shadow_trace(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: Any,
    inbound_message_id: Any,
) -> bool:
    result = await session.execute(
        select(TurnTrace.id)
        .where(
            TurnTrace.tenant_id == tenant_id,
            TurnTrace.conversation_id == _as_uuid(conversation_id),
            TurnTrace.inbound_message_id == _as_uuid(inbound_message_id),
            TurnTrace.router_trigger == SHADOW_ROUTER_TRIGGER,
        )
        .limit(10)
    )
    for trace_id in result.scalars():
        # Router trigger + inbound already makes re-entry unsafe.
        if trace_id is not None:
            return True
    return False


async def _record_shadow_trace(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: Any,
    inbound_text: str,
    inbound_message_id: Any,
    from_phone_e164: str | None,
    deployment: AgentDeployment,
    summary: dict[str, Any],
) -> UUID:
    conversation_uuid = _as_uuid(conversation_id)
    turn_number = (
        await session.execute(
            select(func.coalesce(func.max(TurnTrace.turn_number), 0) + 1).where(
                TurnTrace.conversation_id == conversation_uuid
            )
        )
    ).scalar_one()
    side_effects = summary.get("side_effects") or {}
    trace = TurnTrace(
        tenant_id=tenant_id,
        conversation_id=conversation_uuid,
        turn_number=int(turn_number),
        inbound_message_id=_as_uuid(inbound_message_id),
        inbound_text=inbound_text,
        state_before={
            "conversation_id": str(conversation_uuid),
            "from_phone_e164": from_phone_e164,
            "deployment_id": str(deployment.id),
            "agent_id": str(deployment.agent_id),
        },
        state_after={
            "respond_style": True,
            "phase": "PHASE_18_REAL_TRAFFIC_SHADOW_SOAK_PILOT",
            "mode": "shadow_no_send",
            "route": summary.get("route"),
            "legacy_path_used": summary.get("legacy_path_used"),
            "send_decision": summary.get("send_decision"),
            "send_allowed": summary.get("send_allowed"),
            "outbox_write_attempted": summary.get("outbox_write_attempted"),
            "side_effects": {
                "delivery": bool(side_effects.get("delivery")),
                "workflows": bool(side_effects.get("workflows")),
                "actions": bool(side_effects.get("actions")),
                "field_writes": bool(side_effects.get("field_writes")),
            },
            "operator_review": {
                "required": True,
                "score": None,
                "critical": False,
                "leak": None,
                "unsupported_claims": None,
            },
        },
        composer_input={
            "runtime": "respond_style",
            "mode": "inbound_shadow_no_send",
            "inbound_text": inbound_text,
        },
        composer_output=summary,
        composer_provider="openai",
        outbound_messages=None,
        errors=(
            [{"code": summary["blocked_reason"]}]
            if summary.get("blocked_reason")
            else None
        ),
        bot_paused=False,
        router_trigger=SHADOW_ROUTER_TRIGGER,
        raw_llm_response=json.dumps(summary, ensure_ascii=False, default=str),
        agent_id=deployment.agent_id,
        kb_evidence={
            "tools": summary.get("tools") or [],
            "validator": summary.get("validator") or {},
        },
        rules_evaluated=[
            {"rule": "respond_style_inbound_shadow_enabled", "passed": True},
            {
                "rule": "phone_allowlist",
                "passed": True,
                "from_phone_e164": from_phone_e164,
            },
            {
                "rule": "no_send",
                "passed": summary.get("send_decision") == "no_send",
            },
            {
                "rule": "outbox_zero",
                "passed": summary.get("outbox_write_attempted") is False,
            },
            {
                "rule": "legacy_path_unused",
                "passed": summary.get("legacy_path_used") is False,
            },
        ],
    )
    session.add(trace)
    await session.flush()
    return trace.id


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


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

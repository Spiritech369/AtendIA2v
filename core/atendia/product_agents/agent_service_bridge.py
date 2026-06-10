"""Phase 14 — AgentService bridge to the Respond-Style direct route.

For tenants whose deployment opted into the direct route (resolver preview
``product_agent_direct``), AgentService delegates the turn to
ProductAgentRuntime in MANDATORY no-send mode. Everything else keeps the
previous Runtime V2 path untouched.

Fail-closed rules:
- non-no_send mode requested for an opted-in deployment -> blocked.
- publish gates with blockers -> blocked (never a legacy fallback).
- any bridge error for an opted-in deployment -> blocked, never a crash
  and never silent legacy routing.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from atendia.agent_runtime import (
    ConversationStateSnapshot,
    DryFactsToolExecutor,
    ProductAgentConfigSnapshotAdapter,
    ProductAgentPublishedConfig,
    ProductAgentRuntime,
    ProductAgentRuntimeInput,
    ProductAgentRuntimeResult,
    RespondStyleLLMTurnProvider,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_field_state import apply_field_proposals
from atendia.agent_runtime.respond_style_llm_provider import (
    RespondStyleLLMTurnProviderConfig,
)
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoopConfig
from atendia.config import get_settings
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentVersion,
    RespondStyleShadowFields,
)
from atendia.product_agents.inbound_shadow import _recent_transcript
from atendia.product_agents.publish_gates import respond_style_publish_blockers
from atendia.product_agents.routing_preview import preview_respond_style_routing
from atendia.product_agents.test_lab_direct_adapter import _config_from_version

logger = logging.getLogger(__name__)

AGENT_SERVICE_ROUTE = "respond_style_agent_service_no_send"


class RespondStyleBridgeOutcome:
    """Result of the bridge: either a runtime result (possibly blocked) or
    structured blockers — always no-send. ``None`` from the entrypoint
    means 'not opted in, use the previous path'."""

    def __init__(
        self,
        *,
        result: ProductAgentRuntimeResult | None,
        blocked_reason: str | None = None,
        blockers: list[dict[str, Any]] | None = None,
        deployment_id: str | None = None,
        agent_version_id: str | None = None,
        field_state: dict[str, Any] | None = None,
        no_send_followup: dict[str, Any] | None = None,
    ) -> None:
        self.result = result
        self.blocked_reason = blocked_reason
        self.blockers = blockers or []
        self.deployment_id = deployment_id
        self.agent_version_id = agent_version_id
        self.field_state = field_state or {}
        self.no_send_followup = no_send_followup or derive_no_send_followup(
            result=result, blocked_reason=blocked_reason
        )


async def maybe_handle_respond_style_turn(
    session: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    inbound_text: str,
    mode: str,
) -> RespondStyleBridgeOutcome | None:
    """Returns None when no deployment opted in (previous path continues).
    Otherwise ALWAYS returns a no-send outcome — opted-in turns never fall
    back to the legacy composer path."""
    deployment, ambiguous = await _resolve_opted_in_deployment(
        session, tenant_id=tenant_id
    )
    if ambiguous:
        # 15C: more than one direct-route deployment matches and there is no
        # channel signal to disambiguate -> fail closed, never guess.
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason="respond_style_deployment_ambiguous",
        )
    if deployment is None:
        return None
    try:
        return await _handle_opted_in_turn(
            session,
            deployment=deployment,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
            mode=mode,
        )
    except Exception as exc:  # fail closed: never crash, never legacy-fallback
        logger.exception(
            "respond_style_agent_service_bridge_failed tenant=%s", tenant_id
        )
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason=f"respond_style_bridge_failed:{type(exc).__name__}",
            deployment_id=str(deployment.id),
        )


async def _handle_opted_in_turn(
    session: Any,
    *,
    deployment: AgentDeployment,
    tenant_id: str,
    conversation_id: str,
    inbound_text: str,
    mode: str,
) -> RespondStyleBridgeOutcome:
    if mode != "no_send":
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason="respond_style_live_not_enabled",
            deployment_id=str(deployment.id),
        )

    version = await session.get(AgentVersion, deployment.active_version_id)
    if version is None or str(version.tenant_id) != str(tenant_id):
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason="respond_style_active_version_missing",
            deployment_id=str(deployment.id),
        )

    blockers = await respond_style_publish_blockers(
        session,
        tenant_id=UUID(str(tenant_id)),
        version_id=version.id,
        deployment=deployment,
    )
    if blockers:
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason="respond_style_publish_gates_blocked",
            blockers=blockers,
            deployment_id=str(deployment.id),
            agent_version_id=str(version.id),
        )

    api_key = get_settings().openai_api_key
    if not api_key:
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason="respond_style_provider_unconfigured",
            deployment_id=str(deployment.id),
            agent_version_id=str(version.id),
        )

    config = _config_from_version(version)
    transcript = await _recent_transcript(session, conversation_id=conversation_id)
    shadow_values = await _load_shadow_fields(session, conversation_id=conversation_id)
    state = ConversationStateSnapshot(
        recent_messages=transcript, field_values=shadow_values
    )
    runtime = ProductAgentRuntime(
        snapshot_adapter=_StaticSources(config, state),
        tool_loop=build_tool_loop(config, api_key),
    )
    result = await runtime.run_turn(
        ProductAgentRuntimeInput(
            tenant_id=str(tenant_id),
            agent_id=str(deployment.agent_id),
            conversation_id=str(conversation_id),
            channel=AGENT_SERVICE_ROUTE,
            inbound_text=inbound_text,
        )
    )
    # 15A: validated, audited shadow application of the turn's field
    # proposals — survives across turns; never touches commercial state.
    application = apply_field_proposals(
        result.field_update_proposals,
        field_policies=config.field_definitions,
        current_values=shadow_values,
    )
    if application.audit:
        await _save_shadow_fields(
            session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            application=application,
        )
    return RespondStyleBridgeOutcome(
        result=result,
        deployment_id=str(deployment.id),
        agent_version_id=str(version.id),
        field_state={
            "shadow_only": True,
            "previous_values": shadow_values,
            "new_values": application.new_values,
            "accepted": application.accepted_count,
            "rejected": application.rejected_count,
            "audit": [entry.model_dump(mode="json") for entry in application.audit],
        },
    )


def derive_no_send_followup(
    *,
    result: ProductAgentRuntimeResult | None,
    blocked_reason: str | None,
) -> dict[str, Any]:
    """15B: internal-only policy for blocked/silent turns. In a future live
    context a no_send turn must never be invisible: it raises an internal
    operator/handoff signal. This phase only DECLARES the decision — no
    customer copy, no workflow execution, no delivery."""
    effective_reason = blocked_reason or (
        result.blocked_reason if result is not None else None
    )
    if effective_reason:
        return {
            "action": "handoff_internal_needed",
            "notify_operator": True,
            "reason": effective_reason,
            "customer_copy_sent": False,
            "executed": False,
        }
    if result is not None and result.final_message is None:
        return {
            "action": "handoff_internal_needed",
            "notify_operator": True,
            "reason": "no_visible_message",
            "customer_copy_sent": False,
            "executed": False,
        }
    return {"action": "none", "notify_operator": False, "executed": False}


async def _load_shadow_fields(session: Any, *, conversation_id: str) -> dict[str, Any]:
    row = await session.get(RespondStyleShadowFields, UUID(str(conversation_id)))
    if row is None or not isinstance(row.field_values, dict):
        return {}
    return dict(row.field_values)


async def _save_shadow_fields(
    session: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    application: Any,
) -> None:
    row = await session.get(RespondStyleShadowFields, UUID(str(conversation_id)))
    audit_entries = [entry.model_dump(mode="json") for entry in application.audit]
    if row is None:
        session.add(
            RespondStyleShadowFields(
                conversation_id=UUID(str(conversation_id)),
                tenant_id=UUID(str(tenant_id)),
                field_values=application.new_values,
                audit_log=audit_entries,
            )
        )
    else:
        row.field_values = application.new_values
        row.audit_log = [*list(row.audit_log or []), *audit_entries]
    await session.flush()


def build_tool_loop(
    config: ProductAgentPublishedConfig, api_key: str
) -> RespondStyleToolLoop:
    return RespondStyleToolLoop(
        provider=RespondStyleLLMTurnProvider(
            api_key=api_key,
            config=RespondStyleLLMTurnProviderConfig(),
        ),
        executor=DryFactsToolExecutor(config.tool_bindings),
        config=RespondStyleToolLoopConfig(max_tool_rounds=3, max_elapsed_seconds=120.0),
    )


async def _resolve_opted_in_deployment(
    session: Any,
    *,
    tenant_id: str,
) -> tuple[AgentDeployment | None, bool]:
    """Opt-in = the resolver previews product_agent_direct for a deployment
    (requires metadata respond_style_enabled + published state + active
    version). Returns (deployment, ambiguous): ambiguous=True when more
    than one deployment qualifies and no signal disambiguates."""
    try:
        previews = await preview_respond_style_routing(
            session, tenant_id=UUID(str(tenant_id))
        )
    except Exception:
        logger.debug("respond_style_routing_preview_failed_in_bridge", exc_info=True)
        return None, False
    direct_ids = {
        item["deployment_id"]
        for item in previews
        if item.get("route_preview") == "product_agent_direct"
    }
    if not direct_ids:
        return None, False
    if len(direct_ids) > 1:
        return None, True
    from sqlalchemy import select

    rows = await session.execute(
        select(AgentDeployment).where(AgentDeployment.tenant_id == UUID(str(tenant_id)))
    )
    for deployment in rows.scalars():
        if str(deployment.id) in direct_ids:
            return deployment, False
    return None, False


class _StaticSources:
    """Snapshot adapter over already-loaded config + state."""

    def __init__(
        self,
        config: ProductAgentPublishedConfig,
        state: ConversationStateSnapshot,
    ) -> None:
        self._adapter = ProductAgentConfigSnapshotAdapter(
            config_source=self, state_source=self
        )
        self._config = config
        self._state = state

    def load_config(self, runtime_input):
        return self._config

    def load_state(self, runtime_input):
        return self._state

    def load_snapshot(self, runtime_input):
        return self._adapter.load_snapshot(runtime_input)


__all__ = [
    "AGENT_SERVICE_ROUTE",
    "RespondStyleBridgeOutcome",
    "build_tool_loop",
    "maybe_handle_respond_style_turn",
]

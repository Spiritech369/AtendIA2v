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
from atendia.agent_runtime.respond_style_llm_provider import (
    RespondStyleLLMTurnProviderConfig,
)
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoopConfig
from atendia.config import get_settings
from atendia.db.models.product_agent import AgentDeployment, AgentVersion
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
    ) -> None:
        self.result = result
        self.blocked_reason = blocked_reason
        self.blockers = blockers or []
        self.deployment_id = deployment_id
        self.agent_version_id = agent_version_id


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
    deployment = await _resolve_opted_in_deployment(session, tenant_id=tenant_id)
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
    state = ConversationStateSnapshot(recent_messages=transcript)
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
    return RespondStyleBridgeOutcome(
        result=result,
        deployment_id=str(deployment.id),
        agent_version_id=str(version.id),
    )


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
) -> AgentDeployment | None:
    """Opt-in = the resolver previews product_agent_direct for a deployment
    (requires metadata respond_style_enabled + published state + active
    version)."""
    try:
        previews = await preview_respond_style_routing(
            session, tenant_id=UUID(str(tenant_id))
        )
    except Exception:
        logger.debug("respond_style_routing_preview_failed_in_bridge", exc_info=True)
        return None
    direct_ids = {
        item["deployment_id"]
        for item in previews
        if item.get("route_preview") == "product_agent_direct"
    }
    if not direct_ids:
        return None
    from sqlalchemy import select

    rows = await session.execute(
        select(AgentDeployment).where(AgentDeployment.tenant_id == UUID(str(tenant_id)))
    )
    for deployment in rows.scalars():
        if str(deployment.id) in direct_ids:
            return deployment
    return None


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

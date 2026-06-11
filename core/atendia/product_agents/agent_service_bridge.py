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
        smoke: dict[str, Any] | None = None,
    ) -> None:
        self.result = result
        self.blocked_reason = blocked_reason
        self.blockers = blockers or []
        self.deployment_id = deployment_id
        self.agent_version_id = agent_version_id
        self.field_state = field_state or {}
        self.smoke = smoke or {"active": False, "staged": False}
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
    channel: str | None = None,
    from_phone_e164: str | None = None,
    inbound_message_id: str | None = None,
    reply_channel: str | None = None,
) -> RespondStyleBridgeOutcome | None:
    """Returns None when no deployment opted in (previous path continues).
    Otherwise ALWAYS returns a no-send outcome — opted-in turns never fall
    back to the legacy composer path. ``channel`` disambiguates when more
    than one deployment qualifies (15C)."""
    deployment, ambiguous = await _resolve_opted_in_deployment(
        session, tenant_id=tenant_id, channel=channel
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
            from_phone_e164=from_phone_e164,
            inbound_message_id=inbound_message_id,
            reply_channel=reply_channel,
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
    from_phone_e164: str | None = None,
    inbound_message_id: str | None = None,
    reply_channel: str | None = None,
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

    # Phase 20: accepted-handoff takeover — once a human takeover is
    # pending for this conversation, the direct route stops auto-responding
    # entirely (no LLM call) until a human joins or rollback/reset clears it.
    from atendia.product_agents.smoke_policy import get_takeover_pending

    takeover_pending = await get_takeover_pending(
        session, conversation_id=conversation_id
    )
    if takeover_pending:
        return RespondStyleBridgeOutcome(
            result=None,
            blocked_reason="human_takeover_pending",
            deployment_id=str(deployment.id),
            agent_version_id=str(version.id),
            no_send_followup={
                "action": "human_takeover_pending",
                "notify_operator": False,
                "reason": "handoff accepted; waiting for human",
                "customer_copy_sent": False,
                "executed": False,
            },
            smoke={"active": False, "staged": False, "takeover_pending": True},
        )

    config = _config_from_version(version)
    transcript = await _recent_transcript(session, conversation_id=conversation_id)
    shadow_values, corrected_fields = await _load_shadow_state(
        session, conversation_id=conversation_id
    )
    handoff_pending = await _recent_handoff_pending(
        session, conversation_id=conversation_id
    )
    # Phase 20.1: a turn is a VISIBLE-send candidate only when smoke flags
    # are active, the canonical deployment columns are enabled AND the phone
    # is allowlisted. Such turns run on the REAL facts executor (catalog +
    # Knowledge OS) and the validator enforces real grounding; everything
    # else stays on dry facts in shadow.
    from atendia.product_agents.smoke_policy import (
        canonical_columns_enabled,
        legacy_send_suppressed_for_smoke,
    )

    metadata = dict(deployment.metadata_json or {})
    visible_send_candidate = bool(
        legacy_send_suppressed_for_smoke(metadata, from_phone_e164)
        and canonical_columns_enabled(deployment)
    )
    real_facts: dict[str, Any] | None = None
    if visible_send_candidate:
        from atendia.product_agents.real_tool_facts import load_real_tool_facts

        real_facts = await load_real_tool_facts(session, tenant_id=str(tenant_id))
        # The PROMPT vocabulary must match the REAL catalog too: any
        # referent-checked field gets its allowed_values rebuilt from the
        # real models — harness/demo names can never leak into visible copy
        # via the field vocabulary.
        config = config.model_copy(
            update={
                "field_definitions": _real_allowed_values_for_fields(
                    config.field_definitions, real_facts
                )
            }
        )

    pretool_results = await _vision_pretool_results(
        session,
        inbound_message_id=inbound_message_id,
        api_key=api_key,
        model=metadata.get("respond_style_model") or "gpt-4o",
    )
    state = ConversationStateSnapshot(
        recent_messages=transcript,
        field_values=shadow_values,
        corrected_fields=corrected_fields,
        handoff_pending=handoff_pending,
        visible_send_candidate=visible_send_candidate,
        pretool_results=pretool_results,
    )
    model_override = metadata.get("respond_style_model")
    runtime = ProductAgentRuntime(
        snapshot_adapter=_StaticSources(config, state),
        tool_loop=build_tool_loop(
            config, api_key, model=model_override, real_facts=real_facts
        ),
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
    smoke_info = await _maybe_stage_smoke_send(
        session,
        deployment=deployment,
        version=version,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        from_phone_e164=from_phone_e164,
        result=result,
        reply_channel=reply_channel,
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
        smoke=smoke_info,
    )


async def _maybe_stage_smoke_send(
    session: Any,
    *,
    deployment: AgentDeployment,
    version: AgentVersion,
    tenant_id: str,
    conversation_id: str,
    inbound_message_id: str | None,
    from_phone_e164: str | None,
    result: ProductAgentRuntimeResult,
    reply_channel: str | None = None,
) -> dict[str, Any]:
    """Phase 20: per-turn runtime gate for single-contact smoke. With the
    flags off (the default and the state this phase leaves behind) this is a
    pure no-op. With flags on, ONLY the allowlisted phone can ever stage a
    validated final_message to the existing outbox path; every failure mode
    fails closed and (15B) pages the operator instead of sending anything."""
    from atendia.product_agents.smoke_policy import (
        evaluate_smoke_send,
        notify_operator_fail_closed,
        set_takeover_pending,
        stage_smoke_send,
    )

    metadata = dict(deployment.metadata_json or {})
    evaluation = evaluate_smoke_send(
        metadata=metadata,
        from_phone=from_phone_e164,
        result=result,
        takeover_pending=False,
        deployment=deployment,
    )
    smoke_info: dict[str, Any] = {
        "active": evaluation.active,
        "allowed": evaluation.allowed,
        "staged": False,
        "scope": evaluation.scope,
        "phone_normalized": evaluation.phone_normalized,
        "reasons": list(evaluation.reasons),
    }
    if not evaluation.active:
        return smoke_info
    if evaluation.allowed:
        staged = await stage_smoke_send(
            session,
            tenant_id=str(tenant_id),
            deployment_id=str(deployment.id),
            agent_version_id=str(version.id),
            conversation_id=str(conversation_id),
            inbound_message_id=inbound_message_id,
            to_phone_e164=str(from_phone_e164),
            final_message=str(result.final_message),
            model=metadata.get("respond_style_model"),
            trace_id=(result.trace or {}).get("turn_trace_id"),
            send_scope=str(evaluation.scope),
            validator_status="valid",
            reply_channel=reply_channel,
        )
        smoke_info.update(staged)
        if evaluation.pause_after_send:
            await set_takeover_pending(
                session, tenant_id=str(tenant_id), conversation_id=str(conversation_id)
            )
            smoke_info["takeover_pending_set"] = True
        return smoke_info
    # Smoke is ACTIVE but this turn cannot send. For the allowlisted phone a
    # blocked turn means the customer gets silence — 15B requires paging a
    # human. Non-allowlisted phones simply stay in shadow (no page).
    phone_is_target = "phone_not_allowlisted" not in evaluation.reasons
    turn_failed = bool(result.blocked_reason) or not (result.final_message or "").strip()
    if (
        phone_is_target
        and turn_failed
        and metadata.get("respond_style_fail_closed_notify_operator") is True
    ):
        handoff_id = await notify_operator_fail_closed(
            session,
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            reason=str(result.blocked_reason or "final_message_missing"),
            detail={"smoke_reasons": list(evaluation.reasons)},
        )
        smoke_info["operator_notified"] = True
        smoke_info["operator_handoff_id"] = handoff_id
    return smoke_info


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


async def _vision_pretool_results(
    session: Any,
    *,
    inbound_message_id: str | None,
    api_key: str,
    model: str,
) -> list[dict[str, Any]]:
    """If the inbound message carries an image, review it with vision and
    inject the facts as a pre-executed document.review tool result. Best
    effort: any failure returns no results and the turn proceeds (the
    prompt's media rule then asks the customer what the image shows)."""
    if inbound_message_id is None:
        return []
    try:
        from pathlib import Path

        from atendia.agent_runtime.respond_style_vision import (
            SUPPORTED_IMAGE_TYPES,
            analyze_document_media,
            vision_tool_result,
        )
        from atendia.db.models.message import MessageRow

        message = await session.get(MessageRow, UUID(str(inbound_message_id)))
        media = ((message.metadata_json or {}).get("media") or {}) if message else {}
        mime_type = str(media.get("mime_type") or "")
        url = str(media.get("url") or "")
        if not url or mime_type not in SUPPORTED_IMAGE_TYPES:
            return []
        upload_dir = Path(get_settings().upload_dir)
        relative = url.split("/uploads/", 1)[-1] if "/uploads/" in url else url
        file_path = upload_dir / relative
        if not file_path.exists():
            logger.warning("respond_style_vision_media_missing %s", file_path)
            return []
        facts = await analyze_document_media(
            api_key=api_key,
            image_bytes=file_path.read_bytes(),
            mime_type=mime_type,
            model=model,
        )
        return [vision_tool_result(facts)]
    except Exception:
        logger.warning("respond_style_vision_pretool_failed", exc_info=True)
        return []


async def _recent_handoff_pending(session: Any, *, conversation_id: str) -> bool:
    """W5-B: a handoff proposed in a recent shadow turn with no human having
    joined yet. In shadow nothing resolves a handoff, so without this signal
    the model keeps 're-connecting' forever; in live this same state is where
    bot-pause / human-takeover attaches."""
    try:
        from sqlalchemy import select

        from atendia.db.models.turn_trace import TurnTrace

        rows = await session.execute(
            select(TurnTrace.raw_llm_response)
            .where(
                TurnTrace.conversation_id == UUID(str(conversation_id)),
                TurnTrace.router_trigger == "respond_style_inbound_shadow_auto",
            )
            .order_by(TurnTrace.created_at.desc())
            .limit(3)
        )
        import json as _json

        for raw in rows.scalars():
            if not raw:
                continue
            try:
                summary = _json.loads(raw)
            except (TypeError, ValueError):
                continue
            if summary.get("handoff_proposal"):
                return True
        return False
    except Exception:
        logger.debug("respond_style_handoff_pending_check_failed", exc_info=True)
        return False


async def _load_shadow_fields(session: Any, *, conversation_id: str) -> dict[str, Any]:
    values, _ = await _load_shadow_state(session, conversation_id=conversation_id)
    return values


async def _load_shadow_state(
    session: Any, *, conversation_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (current_values, corrected_fields). corrected_fields maps a
    field_key to its corrected-away PREVIOUS value (Phase 17: lets the
    context mark current state as canonical over older transcript text)."""
    row = await session.get(RespondStyleShadowFields, UUID(str(conversation_id)))
    if row is None or not isinstance(row.field_values, dict):
        return {}, {}
    values = dict(row.field_values)
    return values, _corrected_fields_from_audit(
        list(row.audit_log or []), current_values=values
    )


def _corrected_fields_from_audit(
    audit_log: list[Any],
    *,
    current_values: dict[str, Any],
) -> dict[str, Any]:
    corrected: dict[str, Any] = {}
    for entry in audit_log:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "accepted":
            continue
        if entry.get("reason") != "corrected_previous_value":
            continue
        field_key = entry.get("field_key")
        previous = entry.get("previous_value")
        if not field_key or previous is None:
            continue
        # Only corrections still relevant: the current value differs from
        # the corrected-away one.
        if str(current_values.get(field_key)) != str(previous):
            corrected[str(field_key)] = previous
    return corrected


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


def _real_allowed_values_for_fields(
    field_definitions: list[dict[str, Any]],
    real_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    models = list(real_facts.get("models") or [])
    if not models:
        return field_definitions
    real_groups = [
        {
            "value": model.get("model_id"),
            "aliases": [
                str(alias)
                for alias in [model.get("label"), *(model.get("aliases") or [])]
                if alias
            ],
        }
        for model in models
    ]
    updated: list[dict[str, Any]] = []
    for definition in field_definitions:
        if isinstance(definition, dict) and definition.get("referent_check") is True:
            updated.append({**definition, "allowed_values": real_groups})
        else:
            updated.append(definition)
    return updated


def build_tool_loop(
    config: ProductAgentPublishedConfig,
    api_key: str,
    model: str | None = None,
    real_facts: dict[str, Any] | None = None,
) -> RespondStyleToolLoop:
    provider_config = (
        RespondStyleLLMTurnProviderConfig(model=model)
        if model
        else RespondStyleLLMTurnProviderConfig()
    )
    if real_facts is not None:
        from atendia.agent_runtime.respond_style_real_facts_executor import (
            RealFactsToolExecutor,
        )

        executor = RealFactsToolExecutor(config.tool_bindings, real_facts)
    else:
        # Dry facts are for shadow/Test Lab ONLY; the validator additionally
        # blocks any visible-send-candidate turn grounded on dry facts.
        executor = DryFactsToolExecutor(config.tool_bindings)
    return RespondStyleToolLoop(
        provider=RespondStyleLLMTurnProvider(
            api_key=api_key,
            config=provider_config,
        ),
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=3, max_elapsed_seconds=120.0),
    )


async def _resolve_opted_in_deployment(
    session: Any,
    *,
    tenant_id: str,
    channel: str | None = None,
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
    from sqlalchemy import select

    rows = await session.execute(
        select(AgentDeployment).where(AgentDeployment.tenant_id == UUID(str(tenant_id)))
    )
    candidates = [
        deployment
        for deployment in rows.scalars()
        if str(deployment.id) in direct_ids
    ]
    if channel and len(candidates) > 1:
        # 15C: a channel signal disambiguates multi-deployment tenants.
        channel_matches = [
            deployment for deployment in candidates if deployment.channel == channel
        ]
        if channel_matches:
            candidates = channel_matches
    if len(candidates) > 1:
        return None, True
    if candidates:
        return candidates[0], False
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

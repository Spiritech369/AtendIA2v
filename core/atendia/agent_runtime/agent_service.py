from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.runtime_state_persistence import persist_runtime_v2_turn_state
from atendia.agent_runtime.schemas import TurnContext, TurnInput, TurnOutput
from atendia.agent_runtime.send_adapter import (
    RuntimeV2SendAdapter,
    SendAdapterResult,
    SendMode,
)
from atendia.agent_runtime.send_policy import provider_fallback_detected_from_trace
from atendia.config import get_settings


class AgentServiceResult(BaseModel):
    context: TurnContext
    output: TurnOutput | None = None
    state_persistence: dict[str, Any] = Field(default_factory=dict)
    send: SendAdapterResult
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AgentService:
    """Single DB-backed Runtime V2 turn handler.

    The mode may change only final send behavior. Context building, provider,
    tools, StateWriter, policy validation, state persistence and TurnOutput are
    shared for no-send and live-candidate runs.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        context_builder: ContextBuilder | None = None,
        provider: Any | None = None,
        policy_validator: PolicyValidator | None = None,
        send_adapter: RuntimeV2SendAdapter | None = None,
    ) -> None:
        self._session = session
        self._context_builder = context_builder or ContextBuilder(session)
        self._provider = provider or AdvisorFirstAgentProvider()
        self._policy_validator = policy_validator or PolicyValidator()
        self._send_adapter = send_adapter or RuntimeV2SendAdapter()

    async def handle_turn(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        inbound_text: str,
        turn_number: int,
        mode: SendMode,
        metadata: dict[str, Any] | None = None,
        to_phone_e164: str | None = None,
    ) -> AgentServiceResult:
        # Phase 14: Respond-Style direct route for opted-in Product Agents
        # (mandatory no-send). Tenants without an opted-in deployment keep
        # the previous Runtime V2 path completely untouched.
        from atendia.product_agents.agent_service_bridge import (
            maybe_handle_respond_style_turn,
        )

        respond_style = await maybe_handle_respond_style_turn(
            self._session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
            mode=str(mode),
            channel=(metadata or {}).get("reply_channel")
            or (metadata or {}).get("channel"),
            from_phone_e164=(metadata or {}).get("from_phone_e164"),
            inbound_message_id=(metadata or {}).get("inbound_message_id"),
            reply_channel=(metadata or {}).get("reply_channel"),
        )
        if respond_style is not None:
            return _respond_style_agent_service_result(
                respond_style,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=inbound_text,
                mode=mode,
            )

        metadata = {**(metadata or {}), "agent_service_mode": mode}
        context = await self._context_builder.build(
            TurnInput(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=inbound_text,
                turn_number=turn_number,
                metadata=metadata,
            )
        )
        errors: list[dict[str, Any]] = []
        output: TurnOutput | None = None
        sendable_output: TurnOutput | None = None
        try:
            raw_output = await self._provider.generate(context)
            output = (
                raw_output
                if isinstance(raw_output, TurnOutput)
                else TurnOutput(**raw_output)
            )
            validator = self._policy_validator
            if context.active_agent and context.active_agent.enabled_action_ids is not None:
                validator = PolicyValidator(action_registry_for_agent(context.active_agent))
            validator.validate_or_raise(output)
            required_tool_failures = _required_tool_failures(output.trace_metadata)
            if required_tool_failures:
                errors.append(
                    {
                        "where": "agent_service",
                        "code": "required_tool_not_succeeded_blocks_send",
                        "required_tool_failures": required_tool_failures,
                    }
                )
            else:
                sendable_output = output
        except Exception as exc:
            errors.append(
                {
                    "where": "agent_service",
                    "code": "runtime_v2_turn_failed",
                    "exception": type(exc).__name__,
                    "message": str(exc)[:300],
                }
            )

        state_persistence: dict[str, Any] = {}
        if sendable_output is not None:
            state_persistence = await persist_runtime_v2_turn_state(
                self._session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                output=sendable_output,
            )
            sendable_output.trace_metadata["state_persistence"] = state_persistence

        runtime_config = await _load_agent_runtime_v2_config(self._session, tenant_id)
        if output is not None and _runtime_v2_contract_safe_mode(output.trace_metadata):
            runtime_config = {**runtime_config, "tenant_domain_contract_safe_mode": True}
        contact_id, phone_e164 = await _contact_scope(self._session, conversation_id)
        provider_fallback = (
            provider_fallback_detected_from_trace(output.trace_metadata)
            if output is not None
            else False
        )
        settings = get_settings()
        send = await self._send_adapter.apply(
            mode=mode,
            session=self._session,
            runtime_config=runtime_config,
            global_send_enabled=(
                bool(settings.agent_runtime_v2_enabled)
                and bool(settings.agent_runtime_v2_send_enabled)
            ),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=turn_number,
            contact_id=contact_id,
            phone_e164=phone_e164,
            recipient_phone_e164=to_phone_e164,
            output=sendable_output,
            provider_fallback_detected=provider_fallback,
        )
        errors.extend(send.errors)
        return AgentServiceResult(
            context=context,
            output=output,
            state_persistence=state_persistence,
            send=send,
            errors=errors,
        )


def _respond_style_agent_service_result(
    outcome: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    inbound_text: str,
    mode: SendMode,
) -> AgentServiceResult:
    """Maps a Respond-Style bridge outcome into the AgentServiceResult shape
    consumed by existing callers. Always no-send: the send decision is
    blocked by construction and no outbox write is ever attempted."""
    from atendia.agent_runtime.send_policy import PreparedSendDecision

    result = outcome.result
    blocked_reason = outcome.blocked_reason or (
        result.blocked_reason if result is not None else None
    )
    runtime_trace = dict(result.trace) if result is not None else {}
    provider_trace = runtime_trace.get("respond_style_llm_provider") or {}
    loop_trace = runtime_trace.get("respond_style_tool_loop") or {}
    trace_metadata: dict[str, Any] = {
        "respond_style_agent_service": {
            "route": "respond_style_agent_service_no_send",
            "legacy_path_used": False,
            "send_decision": "no_send",
            "deployment_id": outcome.deployment_id,
            "agent_version_id": outcome.agent_version_id,
            "blocked_reason": blocked_reason,
            "publish_gate_blockers": outcome.blockers,
            "context_summary": {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "inbound_text": inbound_text[:200],
            },
            "tool_rounds": loop_trace.get("tool_rounds"),
            "tool_results": loop_trace.get("tool_results"),
            "dropped_tool_requests": loop_trace.get("dropped_tool_requests"),
            "retry_backoff": {
                "transient_retries_total": provider_trace.get(
                    "transient_retries_total"
                ),
                "validator_retries_total": provider_trace.get(
                    "validator_retries_total"
                ),
                "backoff_wait_ms_total": provider_trace.get("backoff_wait_ms_total"),
            },
            "validator": (result.validation_result if result is not None else {}),
            "final_message_candidate": (
                result.final_message if result is not None else None
            ),
            "field_update_proposals": (
                result.field_update_proposals if result is not None else []
            ),
            "workflow_event_proposals": (
                result.workflow_event_proposals if result is not None else []
            ),
            "action_proposals": (
                result.action_proposals if result is not None else []
            ),
            "handoff_proposal": (
                result.handoff_proposal if result is not None else None
            ),
            "field_state": getattr(outcome, "field_state", {}),
            "no_send_followup": getattr(outcome, "no_send_followup", {}),
            "smoke": getattr(outcome, "smoke", {"active": False, "staged": False}),
            "side_effects": (
                result.side_effects
                if result is not None
                else {
                    "delivery": False,
                    "workflows": False,
                    "actions": False,
                    "field_writes": False,
                }
            ),
        },
        **runtime_trace,
    }
    output = TurnOutput(
        final_message=(result.final_message or "") if result is not None else "",
        trace_metadata=trace_metadata,
    )
    errors: list[dict[str, Any]] = []
    if blocked_reason:
        errors.append(
            {
                "where": "respond_style_agent_service",
                "code": blocked_reason,
                "blockers": outcome.blockers,
            }
        )
    send = SendAdapterResult(
        mode=mode,
        send_decision=PreparedSendDecision(
            status="blocked",
            allowed=False,
            dry_run=True,
            reason="respond_style_agent_service_no_send_only",
            reasons=[blocked_reason] if blocked_reason else [],
        ),
        delivery_status={"status": "not_attempted"},
        outbox_write_attempted=False,
    )
    return AgentServiceResult(
        context=TurnContext(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
            metadata={"runtime_path": "respond_style_agent_service_no_send"},
        ),
        output=output,
        send=send,
        errors=errors,
    )


async def _load_agent_runtime_v2_config(
    session: AsyncSession,
    tenant_id: str,
) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT config FROM tenants WHERE id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
    ).scalar_one_or_none()
    if not isinstance(row, dict):
        return {}
    raw = row.get("agent_runtime_v2") or row.get("agent_runtime_v2_rollout") or {}
    return dict(raw) if isinstance(raw, dict) else {}


async def _contact_scope(
    session: AsyncSession,
    conversation_id: str,
) -> tuple[str | None, str | None]:
    row = (
        await session.execute(
            text(
                """SELECT c.customer_id, cu.phone_e164
                FROM conversations c
                LEFT JOIN customers cu ON cu.id = c.customer_id
                WHERE c.id = :conversation_id"""
            ),
            {"conversation_id": conversation_id},
        )
    ).mappings().first()
    if row is None:
        return None, None
    return (
        str(row["customer_id"]) if row.get("customer_id") else None,
        str(row["phone_e164"]) if row.get("phone_e164") else None,
    )


def _runtime_v2_contract_safe_mode(trace_metadata: dict[str, Any]) -> bool:
    contract = trace_metadata.get("tenant_domain_contract")
    if isinstance(contract, dict) and contract.get("safe_mode") is True:
        return True
    universal = trace_metadata.get("universal_turn_trace")
    if not isinstance(universal, dict):
        return False
    audit = universal.get("audit")
    audit_contract = (
        audit.get("tenant_domain_contract") if isinstance(audit, dict) else None
    )
    return isinstance(audit_contract, dict) and audit_contract.get("safe_mode") is True


def _required_tool_failures(trace_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    required_tools = _required_tool_names(trace_metadata)
    if not required_tools:
        return []
    tool_results = _tool_result_statuses(trace_metadata)
    failures: list[dict[str, Any]] = []
    for tool_name in required_tools:
        statuses = tool_results.get(tool_name, [])
        if "succeeded" not in statuses:
            failures.append(
                {
                    "tool_name": tool_name,
                    "statuses": statuses,
                    "reason": "required_tool_missing_or_not_succeeded",
                }
            )
    return failures


def _required_tool_names(trace_metadata: dict[str, Any]) -> list[str]:
    advisor = trace_metadata.get("advisor_brain")
    if not isinstance(advisor, dict):
        universal = trace_metadata.get("universal_turn_trace")
        if isinstance(universal, dict):
            advisor = universal.get("advisor_brain")
    if not isinstance(advisor, dict):
        return []
    names: list[str] = []
    for item in advisor.get("required_tools") or []:
        name: str | None = None
        required = True
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("tool_name") or item.get("tool_id")
            required = item.get("required", True) is not False
        if name and required:
            names.append(str(name))
    return names


def _tool_result_statuses(trace_metadata: dict[str, Any]) -> dict[str, list[str]]:
    statuses: dict[str, list[str]] = {}
    items = list(trace_metadata.get("tool_results") or [])
    universal = trace_metadata.get("universal_turn_trace")
    if isinstance(universal, dict):
        items.extend(universal.get("tool_results") or [])
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("tool_name") or item.get("tool_id") or item.get("name")
        status = item.get("status")
        if not name or not status:
            continue
        statuses.setdefault(str(name), []).append(str(status))
    return statuses

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.model_provider import build_agent_turn_provider
from atendia.agent_runtime.policy_validator import PolicyValidationError, PolicyValidator
from atendia.agent_runtime.rollout_policy import RolloutDecision, RolloutPolicyService
from atendia.agent_runtime.runtime import AgentRuntime, AgentTurnProvider
from atendia.agent_runtime.schemas import TurnContext, TurnInput, TurnOutput
from atendia.db.models.conversation import Conversation
from atendia.db.models.message import MessageRow
from atendia.db.models.turn_trace import TurnTrace
from atendia.knowledge.os import KnowledgeRetrievalService, SqlAlchemyKnowledgeRepository

SHADOW_RUNTIME_VERSION = "agent_runtime_v2_shadow_v1"
SHADOW_ROUTER_TRIGGER = "agent_runtime_v2_shadow_auto"


@dataclass(frozen=True)
class ShadowRunResult:
    status: str
    trace_id: UUID | None = None
    reasons: list[str] | None = None


class AgentRuntimeShadowService:
    """Run AgentRuntime v2 in shadow against real conversations.

    This service is deliberately side-effect free: it only writes a TurnTrace.
    It never sends outbound messages, executes actions, mutates contact fields,
    moves lifecycle, or emits real workflow events.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: AgentTurnProvider | None = None,
    ) -> None:
        self._session = session
        self._provider = provider

    async def run_shadow_for_inbound(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        inbound_message_id: UUID,
        inbound_text: str | None = None,
        legacy_trace_id: UUID | None = None,
        legacy_output: list[str] | None = None,
    ) -> ShadowRunResult:
        conversation = await self._load_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            return ShadowRunResult("skipped", reasons=["conversation not found"])
        existing = await self._existing_trace(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
        )
        if existing is not None:
            return ShadowRunResult("skipped", trace_id=existing.id, reasons=["already shadowed"])

        rollout = RolloutPolicyService(self._session)
        shadow_decision = await rollout.can_shadow(
            tenant_id=tenant_id,
            agent_id=conversation.assigned_agent_id,
            channel_id=conversation.channel,
        )
        if not shadow_decision.allowed:
            return ShadowRunResult("skipped", reasons=shadow_decision.reasons)
        model_decision = await rollout.can_use_model_provider(
            tenant_id=tenant_id,
            agent_id=conversation.assigned_agent_id,
            channel_id=conversation.channel,
        )
        text = inbound_text or await self._message_text(inbound_message_id) or ""
        context: TurnContext | None = None
        output: TurnOutput | None = None
        policy_issues: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        started = time.perf_counter()
        try:
            context = await self._build_context(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=text,
                agent_id=conversation.assigned_agent_id,
                rollout_decisions=[shadow_decision, model_decision],
                model_provider_allowed=model_decision.allowed,
            )
            runtime = AgentRuntime(
                context_builder=_StaticContextBuilder(context),
                provider=self._provider
                or build_agent_turn_provider(
                    model_provider_allowed=model_decision.allowed,
                ),
            )
            output = await runtime.run_turn(
                TurnInput(
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                    inbound_text=text,
                    metadata=context.metadata,
                )
            )
            policy_issues = [
                {"code": issue.code, "message": issue.message}
                for issue in PolicyValidator(
                    action_registry_for_agent(context.active_agent)
                ).validate(output)
            ]
        except PolicyValidationError as exc:
            policy_issues = [
                {"code": issue.code, "message": issue.message}
                for issue in exc.issues
            ]
        except Exception as exc:  # pragma: no cover - defensive boundary
            errors.append(
                {
                    "where": "agent_runtime_v2_shadow",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )

        trace = await self._record_shadow_trace(
            tenant_id=tenant_id,
            conversation=conversation,
            inbound_message_id=inbound_message_id,
            inbound_text=text,
            context=context,
            output=output,
            policy_issues=policy_issues,
            errors=errors,
            legacy_trace_id=legacy_trace_id,
            legacy_output=legacy_output,
            decisions=[shadow_decision, model_decision],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return ShadowRunResult(
            "failed" if errors or policy_issues else "shadowed",
            trace_id=trace.id,
            reasons=[item.get("message", "") for item in errors] or None,
        )

    async def _load_conversation(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> Conversation | None:
        return (
            await self._session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def _existing_trace(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        inbound_message_id: UUID,
    ) -> TurnTrace | None:
        return (
            await self._session.execute(
                select(TurnTrace)
                .where(
                    TurnTrace.tenant_id == tenant_id,
                    TurnTrace.conversation_id == conversation_id,
                    TurnTrace.inbound_message_id == inbound_message_id,
                    TurnTrace.router_trigger == SHADOW_ROUTER_TRIGGER,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _message_text(self, inbound_message_id: UUID) -> str | None:
        return (
            await self._session.execute(
                select(MessageRow.text).where(MessageRow.id == inbound_message_id)
            )
        ).scalar_one_or_none()

    async def _build_context(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        inbound_text: str,
        agent_id: UUID | None,
        rollout_decisions: list[RolloutDecision],
        model_provider_allowed: bool,
    ) -> TurnContext:
        provider = KnowledgeRetrievalService(SqlAlchemyKnowledgeRepository(self._session))
        return await ContextBuilder(
            session=self._session,
            knowledge_provider=provider,
        ).build(
            TurnInput(
                tenant_id=str(tenant_id),
                conversation_id=str(conversation_id),
                inbound_text=inbound_text,
                metadata={
                    "agent_id": str(agent_id) if agent_id else None,
                    "agent_runtime_v2_shadow": True,
                    "side_effects_allowed": False,
                    "rollout": {
                        **_rollout_payload(rollout_decisions),
                        "model_provider_allowed": model_provider_allowed,
                    },
                },
            )
        )

    async def _record_shadow_trace(
        self,
        *,
        tenant_id: UUID,
        conversation: Conversation,
        inbound_message_id: UUID,
        inbound_text: str,
        context: TurnContext | None,
        output: TurnOutput | None,
        policy_issues: list[dict[str, Any]],
        errors: list[dict[str, Any]],
        legacy_trace_id: UUID | None,
        legacy_output: list[str] | None,
        decisions: list[RolloutDecision],
        latency_ms: int,
    ) -> TurnTrace:
        turn_number = (
            await self._session.execute(
                select(func.coalesce(func.max(TurnTrace.turn_number), 0) + 1).where(
                    TurnTrace.conversation_id == conversation.id
                )
            )
        ).scalar_one()
        v2_output = output.model_dump(mode="json") if output else None
        comparison = _comparison_summary(
            legacy_output=legacy_output or [],
            output=output,
            policy_issues=policy_issues,
            errors=errors,
        )
        trace = TurnTrace(
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            turn_number=int(turn_number),
            inbound_message_id=inbound_message_id,
            inbound_text=inbound_text,
            state_before={
                "conversation_id": str(conversation.id),
                "current_stage": conversation.current_stage,
                "status": conversation.status,
                "legacy_trace_id": str(legacy_trace_id) if legacy_trace_id else None,
            },
            state_after={
                "agent_runtime_v2": True,
                "mode": "shadow_auto",
                "runtime_version": SHADOW_RUNTIME_VERSION,
                "side_effects": {
                    "sent_message": False,
                    "updated_fields": False,
                    "moved_lifecycle": False,
                    "executed_actions": False,
                    "workflow_events_real": False,
                },
                "comparison": comparison,
                "rollout": _rollout_payload(decisions),
            },
            composer_input={
                "runtime": "agent_runtime_v2",
                "mode": "shadow_auto",
                "context_summary": _context_summary(context),
            },
            composer_output=v2_output,
            composer_provider=(
                "openai"
                if output and output.trace_metadata.get("provider") == "openai"
                else "fallback"
            ),
            outbound_messages=None,
            total_latency_ms=latency_ms,
            errors=(policy_issues or errors) or None,
            bot_paused=False,
            router_trigger=SHADOW_ROUTER_TRIGGER,
            raw_llm_response=output.model_dump_json() if output else None,
            agent_id=conversation.assigned_agent_id,
            kb_evidence={
                "citations": [
                    citation.model_dump(mode="json")
                    for citation in (output.knowledge_citations if output else [])
                ],
                "retrieval": context.metadata.get("knowledge", {}) if context else {},
            },
            rules_evaluated=[
                {
                    "idempotency_key": _idempotency_key(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        inbound_message_id=inbound_message_id,
                    ),
                    "passed": True,
                },
                *[
                    {
                        "rollout_capability": decision.capability,
                        "passed": decision.allowed,
                        "reasons": decision.reasons,
                    }
                    for decision in decisions
                ],
                {"rule": "policy_valid", "passed": not policy_issues},
            ],
        )
        self._session.add(trace)
        await self._session.flush()
        return trace


class _StaticContextBuilder:
    def __init__(self, context: TurnContext) -> None:
        self._context = context

    async def build(self, turn_input: TurnInput) -> TurnContext:
        return self._context


def _rollout_payload(decisions: list[RolloutDecision]) -> dict[str, Any]:
    return {decision.capability: decision.model_dump(mode="json") for decision in decisions}


def _context_summary(context: TurnContext | None) -> str:
    if context is None:
        return "context=unavailable"
    return (
        f"tenant={context.tenant_id}; conversation={context.conversation_id}; "
        f"messages={len(context.messages)}; citations={len(context.knowledge_citations)}; "
        f"agent={context.active_agent.id if context.active_agent else 'none'}"
    )


def _comparison_summary(
    *,
    legacy_output: list[str],
    output: TurnOutput | None,
    policy_issues: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    legacy_text = "\n".join(item for item in legacy_output if item)
    v2_text = output.final_message if output else ""
    return {
        "legacy_final_message": legacy_text,
        "v2_final_message": v2_text,
        "v2_confidence": output.confidence if output else None,
        "citations_count": len(output.knowledge_citations) if output else 0,
        "actions_proposed": [action.model_dump(mode="json") for action in output.actions]
        if output
        else [],
        "field_updates_proposed": [
            update.model_dump(mode="json") for update in output.field_updates
        ]
        if output
        else [],
        "lifecycle_update_proposed": (
            output.lifecycle_update.model_dump(mode="json")
            if output and output.lifecycle_update
            else None
        ),
        "policy_valid": not policy_issues,
        "policy_issues": policy_issues,
        "error_count": len(errors),
        "same_text": bool(legacy_text and v2_text and legacy_text.strip() == v2_text.strip()),
    }


def _idempotency_key(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    inbound_message_id: UUID,
) -> str:
    return (
        f"{tenant_id}:{conversation_id}:{inbound_message_id}:"
        f"{SHADOW_RUNTIME_VERSION}"
    )

from __future__ import annotations

from typing import Any, Protocol

from atendia.agent_runtime.composer_quote_context import (
    QuoteSnippetBuilder,
    build_quote_context,
)
from atendia.agent_runtime.conversation_progress import (
    ConversationProgressGuard,
    normalize_composer_progress,
    output_from_progress_result,
)
from atendia.agent_runtime.mandatory_tools import MandatoryToolGuard
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.provider_reliability import (
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
)
from atendia.agent_runtime.quote_safety import QuoteSafetyGuard
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import DeterministicStateWriter, StateWriteResult
from atendia.agent_runtime.tenant_domain_contract import tenant_domain_trace_metadata
from atendia.agent_runtime.tracing import build_trace_metadata
from atendia.agent_runtime.universal_turn_trace import attach_universal_turn_trace


class AdvisorBrainProvider(Protocol):
    async def decide(self, context: TurnContext) -> AdvisorBrainDecision: ...


class ToolLayer(Protocol):
    async def execute(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
    ) -> list[ToolExecutionResult]: ...


class RuntimeComposer(Protocol):
    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput: ...


class DeterministicAdvisorBrain:
    """Minimal advisor brain for tests and local preview.

    It does not classify intents or route by keywords. It packages the current
    context into an advisor decision so the runtime can exercise the target
    architecture without an external model.
    """

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        known_facts = {
            **context.memory.salient_facts,
            **{
                field.key: context.customer.attrs.get(field.key)
                for field in context.contact_fields
                if field.key in context.customer.attrs
            },
        }
        return AdvisorBrainDecision(
            understanding="Customer message should be handled using the full turn context.",
            customer_goal=None,
            conversation_goals=["answer_question", "advance_sale"],
            known_facts=known_facts,
            missing_facts=[],
            next_best_action="respond_with_context",
            required_tools=[],
            proposed_state_changes=[],
            response_plan=(
                "Answer naturally, avoid repeating known facts, and ask one concise "
                "clarification only if needed."
            ),
            confidence=0.72,
            needs_human=False,
            metadata={
                "memory_used": bool(
                    context.memory.summary
                    or context.memory.salient_facts
                    or context.memory.last_quote_snapshot
                    or context.memory.last_pending_question
                ),
                "tenant_ruleset_present": bool(context.tenant_config.ruleset),
            },
        )


class NoopToolLayer:
    async def execute(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
    ) -> list[ToolExecutionResult]:
        del context
        results: list[ToolExecutionResult] = []
        for request in decision.required_tools:
            results.append(
                ToolExecutionResult(
                    tool_name=request.name,
                    status="skipped",
                    data={"reason": "tool handler not configured"},
                    trace_metadata={"required": request.required},
                )
            )
        return results


class StructuredRuntimeComposer:
    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        trace = build_trace_metadata(
            context=context,
            provider="advisor_first_pipeline",
            extra={
                **tenant_domain_trace_metadata(context),
                "architecture": [
                    "context_builder",
                    "advisor_brain",
                    "tool_layer",
                    "policy_validation",
                    "state_update_proposal",
                    "composer",
                ],
                "advisor_brain": decision.model_dump(mode="json"),
                "tool_results": [result.model_dump(mode="json") for result in tool_results],
                "state_writer": {
                    "accepted": state_write_result.accepted,
                    "blocked": state_write_result.blocked,
                    "needs_review": state_write_result.needs_review,
                },
                "state_writer_decisions": state_write_result.decisions,
                "state_writer_summary": {
                    **state_write_result.summary,
                    "safe_mode": context.tenant_config.safe_mode,
                },
                "invalidated_fields": state_write_result.invalidated_fields,
                "policy_warnings": policy_warnings,
            },
        )
        return TurnOutput(
            final_message=(
                "Recibido. Ya estoy tomando en cuenta el contexto que tenemos y te "
                "ayudo con el siguiente paso."
            ),
            confidence=decision.confidence,
            needs_human=decision.needs_human,
            field_updates=state_write_result.field_updates,
            lifecycle_update=state_write_result.lifecycle_update,
            risk_flags=list(decision.risk_flags),
            knowledge_citations=context.knowledge_citations,
            trace_metadata=trace,
        )


class AdvisorFirstAgentProvider:
    def __init__(
        self,
        *,
        advisor_brain: AdvisorBrainProvider | None = None,
        tool_layer: ToolLayer | None = None,
        composer: RuntimeComposer | None = None,
        state_writer: DeterministicStateWriter | None = None,
        policy_validator: PolicyValidator | None = None,
        mandatory_tool_guard: MandatoryToolGuard | None = None,
        quote_safety_guard: QuoteSafetyGuard | None = None,
        conversation_progress_guard: ConversationProgressGuard | None = None,
        reliability_config: ProviderReliabilityConfig | None = None,
        provider_name: str = "advisor_first_pipeline",
        model_name: str = "deterministic",
    ) -> None:
        self._advisor_brain = advisor_brain or DeterministicAdvisorBrain()
        self._tool_layer = tool_layer or NoopToolLayer()
        self._composer = composer or StructuredRuntimeComposer()
        self._state_writer = state_writer or DeterministicStateWriter()
        self._policy_validator = policy_validator or PolicyValidator()
        self._mandatory_tool_guard = mandatory_tool_guard or MandatoryToolGuard()
        self._quote_safety_guard = quote_safety_guard or QuoteSafetyGuard()
        self._conversation_progress_guard = (
            conversation_progress_guard or ConversationProgressGuard()
        )
        self._reliability_config = reliability_config or ProviderReliabilityConfig(
            max_retries=0,
            timeout_s=30.0,
            retry_output_parse_failures=False,
        )
        self._provider_name = provider_name
        self._model_name = model_name

    async def generate(self, context: TurnContext) -> TurnOutput:
        advisor_failed = False
        advisor_reliability = ProviderReliabilityLayer(
            provider=f"{self._provider_name}:advisor_brain",
            model=self._model_name,
            tenant_id=context.tenant_id,
            config=self._reliability_config,
        )
        try:
            decision = await advisor_reliability.execute(
                lambda: self._advisor_brain.decide(context),
                operation_name="advisor_brain",
                idempotency_key=_provider_idempotency_key(context, "advisor_brain"),
            )
            decision = decision.model_copy(
                update={
                    "metadata": {
                        **decision.metadata,
                        "provider_reliability": advisor_reliability.snapshot().to_dict(),
                    }
                }
            )
        except Exception as exc:
            advisor_failed = True
            advisor_reliability.record_fallback_response()
            decision = _safe_advisor_decision(
                context,
                error=exc,
                reliability=advisor_reliability.snapshot().to_dict(),
            )
        if advisor_failed:
            output = _safe_advisor_output(
                context,
                decision=decision,
                reliability={"advisor_brain": advisor_reliability.snapshot().to_dict()},
            )
            progress_ready_output = normalize_composer_progress(context, output)
            progress_result = self._conversation_progress_guard.apply(
                context=context,
                output=progress_ready_output,
            )
            final_output = output_from_progress_result(progress_result)
            return attach_universal_turn_trace(
                context=context,
                decision=decision,
                tool_results=[],
                state_write_result=StateWriteResult(),
                policy_warnings=[],
                output=final_output,
            )
        tool_results = await self._tool_layer.execute(context=context, decision=decision)
        mandatory_pre_evaluation = self._mandatory_tool_guard.evaluate(
            context=context,
            decision=decision,
            tool_results=tool_results,
        )
        state_write_result = self._state_writer.build_updates(
            context=context,
            decision=decision,
            tool_results=tool_results,
        )
        policy_warnings = self._validate_decision_shape(decision, tool_results)
        policy_warnings.extend(_mandatory_tool_policy_warnings(mandatory_pre_evaluation))
        composer_reliability = ProviderReliabilityLayer(
            provider=f"{self._provider_name}:composer",
            model=self._model_name,
            tenant_id=context.tenant_id,
            config=self._reliability_config,
        )
        try:
            output = await composer_reliability.execute(
                lambda: self._composer.compose(
                    context=context,
                    decision=decision,
                    tool_results=tool_results,
                    state_write_result=state_write_result,
                    policy_warnings=policy_warnings,
                ),
                operation_name="composer",
                idempotency_key=_provider_idempotency_key(context, "composer"),
            )
            output.trace_metadata["provider_reliability"] = {
                "advisor_brain": advisor_reliability.snapshot().to_dict(),
                "composer": composer_reliability.snapshot().to_dict(),
            }
        except Exception as exc:
            composer_reliability.record_fallback_response()
            output = _safe_composer_fallback(
                context=context,
                decision=decision,
                tool_results=tool_results,
                state_write_result=state_write_result,
                policy_warnings=policy_warnings,
                error=exc,
                reliability={
                    "advisor_brain": advisor_reliability.snapshot().to_dict(),
                    "composer": composer_reliability.snapshot().to_dict(),
                },
            )
        mandatory_result = self._mandatory_tool_guard.apply(
            context=context,
            decision=decision,
            tool_results=tool_results,
            output=output,
            pre_evaluation=mandatory_pre_evaluation,
            defer_quote_final_message=True,
        )
        output = mandatory_result.output
        quote_safe_output = self._quote_safety_guard.apply(
            context=context,
            output=output,
            tool_results=tool_results,
        ).output
        progress_ready_output = normalize_composer_progress(context, quote_safe_output)
        progress_result = self._conversation_progress_guard.apply(
            context=context,
            output=progress_ready_output,
        )
        final_output = output_from_progress_result(progress_result)
        return attach_universal_turn_trace(
            context=context,
            decision=decision,
            tool_results=tool_results,
            state_write_result=state_write_result,
            policy_warnings=policy_warnings,
            output=final_output,
        )

    def _validate_decision_shape(
        self,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
    ) -> list[dict[str, str]]:
        del self
        warnings: list[dict[str, str]] = []
        if not decision.next_best_action:
            warnings.append(
                {
                    "code": "missing_next_best_action",
                    "message": "Advisor decision did not include a next action.",
                }
            )
        for result in tool_results:
            if result.status == "failed":
                warnings.append(
                    {
                        "code": "tool_failed",
                        "message": f"Tool {result.tool_name!r} failed.",
                    }
                )
        return warnings


def _provider_idempotency_key(context: TurnContext, component: str) -> str:
    message_id = context.metadata.get("message_id") or context.metadata.get("inbound_message_id")
    turn_id = context.metadata.get("turn_id") or context.metadata.get("turn_number")
    return "|".join(
        [
            str(context.tenant_id),
            str(context.conversation_id),
            str(turn_id or "turn"),
            str(message_id or context.inbound_text),
            component,
        ]
    )


def _safe_advisor_decision(
    context: TurnContext,
    *,
    error: BaseException,
    reliability: dict[str, Any],
) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Provider failed before AdvisorBrain could produce a trusted decision.",
        customer_goal="human_review",
        conversation_goals=["handoff"],
        known_facts=dict(context.memory.salient_facts),
        missing_facts=[],
        next_best_action="human_review",
        required_tools=[],
        proposed_state_changes=[],
        response_plan="Use a safe response without prices or unverified execution promises.",
        confidence=0.0,
        needs_human=True,
        risk_flags=["advisor_brain_provider_failed"],
        metadata={
            "provider_error_type": type(error).__name__,
            "provider_reliability": reliability,
            "fallback": "safe_advisor_brain",
        },
    )


def _safe_advisor_output(
    context: TurnContext,
    *,
    decision: AdvisorBrainDecision,
    reliability: dict[str, Any],
) -> TurnOutput:
    trace = build_trace_metadata(
        context=context,
        provider="advisor_first_pipeline",
            extra={
                **tenant_domain_trace_metadata(context),
                "architecture": ["context_builder", "advisor_brain_fallback"],
            "advisor_brain": decision.model_dump(mode="json"),
            "provider_reliability": reliability,
            "fallback": "safe_advisor_brain",
            "human_review_notes": ["advisor_brain_provider_error"],
        },
    )
    return TurnOutput(
        final_message=(
            "Necesito que una persona del equipo revise esto para responderte con certeza."
        ),
        confidence=0.0,
        needs_human=True,
        risk_flags=list(decision.risk_flags),
        knowledge_citations=context.knowledge_citations,
        trace_metadata=trace,
    )


def _safe_composer_fallback(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
    policy_warnings: list[dict[str, str]],
    error: BaseException,
    reliability: dict[str, Any],
) -> TurnOutput:
    quote_context = build_quote_context(context=context, tool_results=tool_results)
    requirements = _requirements_from_tool_results(tool_results)
    handoff_created = any(
        result.tool_name in {"handoff.request", "handoff.create"}
        and result.status == "succeeded"
        and bool(result.data.get("handoff_required") or result.data.get("handoff_created"))
        for result in tool_results
    )
    if quote_context.can_quote and quote_context.quote_snapshot:
        snippet = QuoteSnippetBuilder().build(quote_context.quote_snapshot)
        message = f"Perfecto, uso la cotizacion validada del sistema. {snippet}"
        field_updates = list(state_write_result.field_updates)
        fallback_kind = "deterministic_quote_snippet"
    elif requirements:
        joined = ", ".join(requirements)
        message = f"Para este paso ocupas: {joined}. Los revisamos con el equipo antes de avanzar."
        field_updates = list(state_write_result.field_updates)
        fallback_kind = "deterministic_requirements_template"
    elif handoff_created:
        message = "Listo, ya quedo solicitado el apoyo de una persona del equipo."
        field_updates = list(state_write_result.field_updates)
        fallback_kind = "deterministic_handoff_created_template"
    else:
        message = "Necesito que una persona del equipo revise esto para responderte con certeza."
        field_updates = []
        fallback_kind = "safe_no_price"
    trace = build_trace_metadata(
        context=context,
        provider="advisor_first_pipeline",
            extra={
                **tenant_domain_trace_metadata(context),
                "architecture": [
                    "context_builder",
                "advisor_brain",
                "tool_layer",
                "policy_validation",
                "state_update_proposal",
                "composer_fallback",
            ],
            "advisor_brain": decision.model_dump(mode="json"),
            "tool_results": [result.model_dump(mode="json") for result in tool_results],
            "state_writer": {
                "accepted": state_write_result.accepted,
                "blocked": state_write_result.blocked,
                "needs_review": state_write_result.needs_review,
            },
            "state_writer_decisions": state_write_result.decisions,
            "state_writer_summary": {
                **state_write_result.summary,
                "safe_mode": context.tenant_config.safe_mode,
            },
            "invalidated_fields": state_write_result.invalidated_fields,
            "policy_warnings": policy_warnings,
            "human_review_notes": [f"composer_provider_error:{type(error).__name__}"],
            "provider_reliability": reliability,
            "fallback": fallback_kind,
        },
    )
    return TurnOutput(
        final_message=message,
        confidence=min(decision.confidence, 0.5),
        needs_human=decision.needs_human or fallback_kind == "safe_no_price",
        field_updates=field_updates,
        lifecycle_update=state_write_result.lifecycle_update,
        risk_flags=[*decision.risk_flags, "composer_provider_failed"],
        knowledge_citations=context.knowledge_citations,
        trace_metadata=trace,
    )


def _requirements_from_tool_results(tool_results: list[ToolExecutionResult]) -> list[str]:
    for result in tool_results:
        requirements = result.data.get("requirements")
        if isinstance(requirements, list):
            return [str(item) for item in requirements if str(item).strip()]
    return []


def _mandatory_tool_policy_warnings(evaluation: Any) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for decision in getattr(evaluation, "blocking_decisions", []):
        warnings.append(
            {
                "code": "mandatory_tool_missing",
                "message": (
                    f"Tool {decision.tool_id!r} is required for {decision.topic!r} "
                    f"but status is {decision.status!r}."
                ),
            }
        )
    return warnings


__all__ = [
    "AdvisorBrainProvider",
    "AdvisorFirstAgentProvider",
    "DeterministicAdvisorBrain",
    "NoopToolLayer",
    "RuntimeComposer",
    "StructuredRuntimeComposer",
    "ToolLayer",
]

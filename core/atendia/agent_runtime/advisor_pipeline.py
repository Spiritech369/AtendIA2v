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
from atendia.agent_runtime.human_response_composer import HumanResponseComposer
from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
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
from atendia.agent_runtime.semantic_interpreter import SemanticAdvisorBrain
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
        final_message = _compose_validated_final_message(
            context=context,
            decision=decision,
            tool_results=tool_results,
            state_write_result=state_write_result,
        )
        pending_slot = _composer_pending_slot(
            context=context,
            tool_results=tool_results,
            state_write_result=state_write_result,
        )
        if pending_slot:
            advisor_trace = dict(trace.get("advisor_brain") or {})
            advisor_metadata = dict(advisor_trace.get("metadata") or {})
            advisor_trace["question_slot"] = pending_slot
            advisor_metadata["missing_field"] = pending_slot
            advisor_trace["metadata"] = advisor_metadata
            trace["advisor_brain"] = advisor_trace
            trace["question_slot"] = pending_slot
        return TurnOutput(
            final_message=final_message,
            confidence=decision.confidence,
            needs_human=decision.needs_human,
            field_updates=state_write_result.field_updates,
            lifecycle_update=state_write_result.lifecycle_update,
            risk_flags=list(decision.risk_flags),
            knowledge_citations=context.knowledge_citations,
            trace_metadata=trace,
        )


def _compose_validated_final_message(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
) -> str:
    if _customer_will_send_document(decision):
        return (
            "Va, cuando me la mandes que sea frente y reverso, completa y legible. "
            "Ahorita aún me falta recibirla."
        )

    expediente = _tool_data(tool_results, "expediente.evaluate")
    if expediente:
        message = _expediente_message(expediente)
        if message:
            return message

    requirements = _tool_data(tool_results, "requirements.lookup")
    if requirements:
        docs = [str(item) for item in requirements.get("requirements") or [] if str(item)]
        if docs and _asks_for_requirements(decision):
            return "Para ese plan ocupas: " + "; ".join(docs) + "."

    quote = _tool_data(tool_results, "quote.resolve")
    if quote:
        snippet = _quote_snippet(quote.get("quote_snapshot"))
        if snippet:
            return f"{snippet} Para avanzar, dime si quieres seguir con la revisión."

    if requirements:
        docs = [str(item) for item in requirements.get("requirements") or [] if str(item)]
        if docs:
            return "Para ese plan ocupas: " + "; ".join(docs) + "."

    credit_plan = _tool_data(tool_results, "credit_plan.resolve")
    if credit_plan:
        if credit_plan.get("needs_clarification"):
            return _credit_plan_clarification_message(context, credit_plan)
        if not _current_seniority(context, state_write_result):
            return (
                "Perfecto, ya validé tu tipo de ingreso para el plan. "
                "¿Cuánto tiempo llevas trabajando?"
            )
        return "Perfecto, ya validé tu tipo de ingreso para el plan."

    if _asks_for_clarification(context):
        return _pending_slot_message(context, decision, state_write_result)

    if _asks_for_requirements(decision) and not requirements:
        if not _current_plan(context, state_write_result):
            return "Para darte la lista exacta dime cómo recibes tus ingresos."
        return "Necesito consultar la lista vigente antes de pedirte algo concreto."

    missing = _current_missing_field(decision)
    if missing in {"income_type", "plan", "plan_credito"}:
        customer_act = _customer_turn_act(decision, context)
        if customer_act == "greeting":
            return _greeting_continuation_message(context, state_write_result)
        if customer_act in {"confusion", "frustration"}:
            return _pending_slot_state_message()
        return (
            "Sí se puede revisar; para darte el plan correcto dime cómo recibes "
            "tus ingresos."
        )
    if missing in {"seniority", "employment_seniority"}:
        return "Me falta saber cuánto tiempo llevas trabajando."

    if decision.needs_human:
        return "Necesito que una persona del equipo revise esto para responderte con certeza."

    return "Dime qué dato quieres revisar."


def _tool_data(tool_results: list[ToolExecutionResult], tool_name: str) -> dict[str, Any]:
    for result in tool_results:
        if result.tool_name == tool_name and result.status == "succeeded":
            return dict(result.data)
    return {}


def _policy_safe_pending_question(trace: dict[str, Any]) -> str | None:
    plan = trace.get("validated_response_plan")
    if not isinstance(plan, dict):
        return None
    question = str(plan.get("next_best_question") or "").strip()
    if not question:
        return None
    message_goal = str(plan.get("message_goal") or "")
    if message_goal not in {
        "ask_one_clarifying_question_for_pending_slot",
        "greet_and_resume_without_consuming_slot",
        "acknowledge_confusion_and_explain_pending_slot",
    }:
        return None
    if question.endswith(("?", "!", ".")):
        return question
    return f"{question}?"


def _quote_snippet(snapshot: Any) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    product = dict(snapshot.get("product") or {})
    pricing = dict(snapshot.get("pricing") or {})
    product_name = str(product.get("display_name") or product.get("sku") or "la moto")
    plan = str(snapshot.get("plan_name") or snapshot.get("plan_code") or "plan validado")
    down = pricing.get("down_payment")
    installment = pricing.get("installment")
    installments = pricing.get("installments")
    period = str(pricing.get("period_label") or "pagos")
    cash_price = pricing.get("cash_price")
    if down and installment and installments:
        return (
            f"Para {product_name} con {plan}, el enganche es de ${int(down):,} "
            f"y los pagos son de ${int(installment):,} por {installments} {period}."
        )
    if cash_price:
        return f"De contado, {product_name} queda en ${int(cash_price):,}."
    return None


def _expediente_message(expediente: dict[str, Any]) -> str | None:
    checklist = expediente.get("Docs_Checklist")
    if not isinstance(checklist, dict):
        return None
    items = [item for item in checklist.get("items") or [] if isinstance(item, dict)]
    received_labels = [
        _friendly_document_label(item)
        for item in items
        if int(item.get("received_count") or 0) > 0
    ]
    if not received_labels:
        return "Todavia no tengo documentos suficientes para revisar el expediente."
    payroll = next(
        (item for item in items if "nomina" in str(item.get("key") or "").casefold()),
        None,
    )
    if payroll and int(payroll.get("missing_count") or 0) > 0:
        missing = int(payroll.get("missing_count") or 0)
        periodicity = str(payroll.get("periodicity") or "semanal")
        faltan = "falta" if missing == 1 else "faltan"
        return (
            f"Ya tengo {_join_spanish_list(received_labels)}. Como tu pago es {periodicity}, "
            f"todavia {faltan} {missing} recibos para completar el mes dentro del "
            f"estado de cuenta."
        )
    if expediente.get("requirements_complete") is True:
        return "Ya tengo los documentos recibidos para revisarlos internamente."
    missing_labels = [
        str(item.get("label") or item.get("key"))
        for item in checklist.get("missing_documents") or []
        if isinstance(item, dict)
    ]
    if missing_labels:
        return (
            "Ya tengo "
            + _join_spanish_list(received_labels)
            + ". Me falta: "
            + ", ".join(missing_labels)
            + "."
        )
    return None


def _friendly_document_label(item: dict[str, Any]) -> str:
    key = str(item.get("key") or "").casefold()
    received_count = int(item.get("received_count") or 0)
    if "ine" in key:
        return "tu INE"
    if "domicilio" in key:
        return "comprobante"
    if "nomina" in key:
        recibo = "recibo" if received_count == 1 else "recibos"
        return f"{received_count} {recibo} de nomina"
    if "estado" in key or "cuenta" in key:
        return "estados de cuenta"
    return str(item.get("label") or key)


def _join_spanish_list(values: list[str]) -> str:
    if len(values) <= 1:
        return "".join(values)
    return ", ".join(values[:-1]) + " y " + values[-1]


def _customer_will_send_document(decision: AdvisorBrainDecision) -> bool:
    text = _semantic_text(decision)
    return any(
        token in text
        for token in (
            "document_future_promise",
            "will_send_document",
            "promesa_documento",
            "send_document_later",
        )
    )


def _asks_for_requirements(decision: AdvisorBrainDecision) -> bool:
    text = _semantic_text(decision)
    return any(token in text for token in ("requirement", "requisito", "document", "papel"))


def _asks_for_clarification(context: TurnContext) -> bool:
    text = str(context.inbound_text or "").strip()
    return bool(text) and all(char in "¿?!. " for char in text)


def _pending_slot_message(
    context: TurnContext,
    decision: AdvisorBrainDecision,
    state_write_result: StateWriteResult,
) -> str:
    slot = (
        str(context.memory.metadata.get("pending_slot") or "")
        or _current_missing_field(decision)
    )
    if slot in {"income_type", "plan", "plan_credito"} and not _current_plan(
        context,
        state_write_result,
    ):
        return "Me falta saber cómo te pagan para darte el plan correcto."
    if slot in {"seniority", "employment_seniority"}:
        return "Me falta saber cuánto tiempo llevas trabajando."
    if slot in {"requirements", "documents", "document"}:
        return "Aún me falta recibirla para revisarla."
    return "Dime qué dato quieres revisar."


def _credit_plan_clarification_message(
    context: TurnContext,
    credit_plan: dict[str, Any],
) -> str:
    flow_policy = _tenant_flow_policy(context)
    clarification = dict(credit_plan.get("clarification") or {})
    if (
        clarification.get("code") == "income_business_tax_status_required"
        and isinstance(flow_policy.get("business_activity_clarification"), str)
    ):
        return str(flow_policy["business_activity_clarification"])
    return "Para darte el plan correcto dime como compruebas tus ingresos."


def _tenant_flow_policy(context: TurnContext) -> dict[str, Any]:
    contract = context.tenant_config.tenant_domain_contract
    if isinstance(contract, dict) and isinstance(contract.get("flow_policy"), dict):
        return dict(contract["flow_policy"])
    contract = context.tenant_config.metadata.get("tenant_domain_contract")
    if isinstance(contract, dict) and isinstance(contract.get("flow_policy"), dict):
        return dict(contract["flow_policy"])
    return {}


def _composer_pending_slot(
    *,
    context: TurnContext,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
) -> str | None:
    credit_plan = _tool_data(tool_results, "credit_plan.resolve")
    if credit_plan.get("needs_clarification"):
        pending_slot = credit_plan.get("pending_slot")
        return str(pending_slot).strip() if pending_slot else None
    if credit_plan and not _current_seniority(context, state_write_result):
        return "employment_seniority"
    return None


def _current_missing_field(decision: AdvisorBrainDecision) -> str:
    return str(decision.metadata.get("missing_field") or decision.question_slot or "").strip()


def _customer_turn_act(decision: AdvisorBrainDecision, context: TurnContext) -> str:
    raw = str(
        decision.latest_customer_act or decision.metadata.get("user_act") or ""
    ).strip()
    if raw and raw != "unknown":
        return raw
    if _is_greeting_only_turn(context):
        return "greeting"
    return "unknown"


def _is_greeting_only_turn(context: TurnContext) -> bool:
    lines = [line.strip() for line in str(context.inbound_text or "").splitlines()]
    meaningful_lines = [line for line in lines if line]
    if not meaningful_lines:
        return False
    return all(_is_greeting_text(line) for line in meaningful_lines)


def _is_greeting_text(text: str) -> bool:
    normalized = text.casefold().strip(" \t\r\n.!,;:?-_()[]{}'\"")
    return normalized in {
        "hola",
        "ola",
        "buen dia",
        "buenos dias",
        "buenas",
        "buenas tardes",
        "buenas noches",
        "hey",
    }


def _greeting_continuation_message(
    context: TurnContext,
    state_write_result: StateWriteResult,
) -> str:
    if _current_value(context, state_write_result, "product_selection"):
        return "Hola, claro. Seguimos con esa opcion o quieres revisar otra?"
    return "Hola, claro. Que te gustaria revisar?"


def _pending_slot_state_message() -> str:
    return (
        "Entiendo. Aun tengo pendiente validar como recibes tus ingresos; "
        "con ese dato puedo avanzar sin adivinar el plan."
    )


def _semantic_text(decision: AdvisorBrainDecision) -> str:
    return " ".join(
        [
            str(decision.customer_goal or ""),
            str(decision.understanding or ""),
            str(decision.response_plan or ""),
            str(decision.metadata.get("income") or ""),
        ]
    ).casefold()


def _current_plan(context: TurnContext, state_write_result: StateWriteResult) -> Any:
    return _current_value(context, state_write_result, "plan_selection")


def _current_seniority(context: TurnContext, state_write_result: StateWriteResult) -> Any:
    return _current_value(context, state_write_result, "employment_seniority")


def _current_value(
    context: TurnContext,
    state_write_result: StateWriteResult,
    key: str,
) -> Any:
    for update in reversed(state_write_result.field_updates):
        if update.field_key == key:
            return update.value
    if key in context.customer.attrs:
        return context.customer.attrs.get(key)
    if key in context.memory.salient_facts:
        return context.memory.salient_facts.get(key)
    return None


class AdvisorFirstAgentProvider:
    def __init__(
        self,
        *,
        advisor_brain: AdvisorBrainProvider | None = None,
        tool_layer: ToolLayer | None = None,
        composer: RuntimeComposer | None = None,
        human_response_composer: RuntimeComposer | None = None,
        state_writer: DeterministicStateWriter | None = None,
        policy_validator: PolicyValidator | None = None,
        mandatory_tool_guard: MandatoryToolGuard | None = None,
        quote_safety_guard: QuoteSafetyGuard | None = None,
        conversation_progress_guard: ConversationProgressGuard | None = None,
        reliability_config: ProviderReliabilityConfig | None = None,
        provider_name: str = "advisor_first_pipeline",
        model_name: str = "deterministic",
    ) -> None:
        self._advisor_brain = advisor_brain or SemanticAdvisorBrain()
        self._tool_layer = tool_layer or TenantKnowledgeToolLayer()
        self._composer = composer or StructuredRuntimeComposer()
        self._human_response_composer = human_response_composer or HumanResponseComposer()
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
            composer = (
                self._human_response_composer
                if _semantic_interpreter_decision(decision)
                else self._composer
            )
            output = await composer_reliability.execute(
                lambda: composer.compose(
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
        quote_safe_output = self._apply_policy_validator(quote_safe_output)
        if _semantic_interpreter_decision(decision):
            final_output = quote_safe_output
        else:
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

    def _apply_policy_validator(self, output: TurnOutput) -> TurnOutput:
        issues = self._policy_validator.validate(output)
        if not issues:
            return output
        trace = dict(output.trace_metadata)
        trace["policy_validator"] = {
            "status": "blocked",
            "issues": [
                {"code": issue.code, "message": issue.message}
                for issue in issues
            ],
        }
        safe_message = _policy_safe_pending_question(trace) or (
            "Necesito que una persona del equipo revise esto para responderte con certeza."
        )
        return output.model_copy(
            update={
                "final_message": safe_message,
                "confidence": min(output.confidence, 0.4),
                "needs_human": True,
                "risk_flags": [
                    *list(output.risk_flags),
                    "policy_validator_blocked",
                    *[issue.code for issue in issues],
                ],
                "trace_metadata": trace,
            }
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


def _semantic_interpreter_decision(decision: AdvisorBrainDecision) -> bool:
    return bool(decision.metadata.get("semantic_interpreter"))


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

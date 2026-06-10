from __future__ import annotations

import json
import re
import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.agent_runtime.tenant_domain_contract import tenant_domain_trace_metadata
from atendia.agent_runtime.tracing import build_trace_metadata
from atendia.agent_runtime.validated_response_plan import (
    DEFAULT_FORBIDDEN_PHRASES,
    ValidatedResponsePlan,
    ValidatedResponsePlanBuilder,
)
from atendia.config import get_settings

_PRICE_RE = re.compile(r"(?:\$|\b\d+[,.]?\d*\s*(?:pesos|mxn|quincenas?|semanas?))", re.I)
_REQUIREMENTS_RE = re.compile(
    r"(?:ine|comprobante de domicilio|recibos?|estado de cuenta|papeles)",
    re.I,
)
_INTERNAL_RE = re.compile(r"(?:json|trace|tool|herramienta|prompt|workflow|outbox)", re.I)
_STATE_WRITER_INTERNAL_RE = re.compile(
    r"(?:field_not_visible|campo\s+no\s+est[aá]\s+visible|statewriter|state writer)",
    re.I,
)
SAFE_HUMAN_REVIEW_MESSAGE = (
    "Necesito que una persona del equipo revise esto para responderte con certeza."
)


class HumanResponseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_message_candidate: str
    language: str = "es"
    reasoning_summary_safe: str = ""
    used_facts: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class HumanResponseComposerProvider(Protocol):
    async def compose(self, plan: ValidatedResponsePlan) -> HumanResponseCandidate: ...


class ChatGPTHumanResponseComposerProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._client = client
        self._model = model
        self.last_usage: dict[str, int] = {}

    async def compose(self, plan: ValidatedResponsePlan) -> HumanResponseCandidate:
        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=[
                {"role": "system", "content": _human_response_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(plan.model_dump(mode="json"), ensure_ascii=False),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": human_response_json_schema(),
            },
            temperature=0.2,
            max_tokens=350,
        )
        self.last_usage = _response_usage(response)
        raw = response.choices[0].message.content or ""
        return HumanResponseCandidate.model_validate_json(raw)


class UnavailableHumanResponseComposerProvider:
    async def compose(self, plan: ValidatedResponsePlan) -> HumanResponseCandidate:
        del plan
        raise RuntimeError("human_response_composer_provider_unavailable")


class HumanResponseComposer:
    def __init__(
        self,
        *,
        provider: HumanResponseComposerProvider | None = None,
        plan_builder: ValidatedResponsePlanBuilder | None = None,
    ) -> None:
        self._provider = provider or build_human_response_provider()
        self._plan_builder = plan_builder or ValidatedResponsePlanBuilder()

    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        plan = self._plan_builder.build(
            context=context,
            decision=decision,
            tool_results=tool_results,
            state_write_result=state_write_result,
            policy_warnings=policy_warnings,
        )
        started = time.perf_counter()
        try:
            candidate = await self._provider.compose(plan)
        except Exception as exc:
            safe_repair = _safe_provider_failure_repair(plan, str(exc))
            if safe_repair is not None:
                trace = _trace(
                    context=context,
                    decision=decision,
                    tool_results=tool_results,
                    state_write_result=state_write_result,
                    plan=plan,
                    candidate=safe_repair,
                    policy_issues=[
                        {
                            "code": "human_response_composer_provider_failed_repaired",
                            "message": "provider failed; replied with validated pending question",
                        }
                    ],
                    latency_ms=_latency_ms(started),
                    model_usage=_provider_usage(self._provider),
                )
                return TurnOutput(
                    final_message=safe_repair.final_message_candidate.strip(),
                    confidence=min(decision.confidence, 0.55),
                    needs_human=False,
                    field_updates=state_write_result.field_updates,
                    lifecycle_update=state_write_result.lifecycle_update,
                    risk_flags=[
                        *list(decision.risk_flags),
                        "human_response_provider_failed_repaired",
                    ],
                    knowledge_citations=context.knowledge_citations,
                    trace_metadata=trace,
                )
            return _fail_closed_output(
                context=context,
                decision=decision,
                tool_results=tool_results,
                state_write_result=state_write_result,
                plan=plan,
                reason="human_response_composer_provider_failed",
                error=str(exc),
                latency_ms=_latency_ms(started),
            )
        policy_issues = validate_human_response_candidate(plan, candidate)
        repair = _safe_slot_question_repair(plan, candidate, policy_issues)
        if repair is not None:
            candidate = repair
            policy_issues = validate_human_response_candidate(plan, candidate)
        trace = _trace(
            context=context,
            decision=decision,
            tool_results=tool_results,
            state_write_result=state_write_result,
            plan=plan,
            candidate=candidate,
            policy_issues=policy_issues,
            latency_ms=_latency_ms(started),
            model_usage=_provider_usage(self._provider),
        )
        if policy_issues or not plan.can_send_visible:
            return TurnOutput(
                final_message=SAFE_HUMAN_REVIEW_MESSAGE,
                confidence=min(decision.confidence, 0.4),
                needs_human=True,
                field_updates=state_write_result.field_updates,
                lifecycle_update=state_write_result.lifecycle_update,
                risk_flags=[
                    *list(decision.risk_flags),
                    "human_response_policy_blocked",
                    *[issue["code"] for issue in policy_issues],
                ],
                knowledge_citations=context.knowledge_citations,
                trace_metadata=trace,
            )
        return TurnOutput(
            final_message=candidate.final_message_candidate.strip(),
            confidence=decision.confidence,
            needs_human=decision.needs_human,
            field_updates=state_write_result.field_updates,
            lifecycle_update=state_write_result.lifecycle_update,
            risk_flags=[*list(decision.risk_flags), *candidate.risk_flags],
            knowledge_citations=context.knowledge_citations,
            trace_metadata=trace,
        )


def build_human_response_provider() -> HumanResponseComposerProvider:
    settings = get_settings()
    if not settings.openai_api_key:
        return UnavailableHumanResponseComposerProvider()
    return ChatGPTHumanResponseComposerProvider(
        api_key=settings.openai_api_key,
        model=settings.composer_model or settings.agent_runtime_v2_model,
        timeout_s=settings.composer_timeout_s,
    )


def validate_human_response_candidate(
    plan: ValidatedResponsePlan,
    candidate: HumanResponseCandidate,
) -> list[dict[str, str]]:
    message = candidate.final_message_candidate.strip()
    issues: list[dict[str, str]] = []
    if not message:
        issues.append({"code": "empty_final_message", "message": "final message is empty"})
    folded = _fold(message)
    for phrase in [*DEFAULT_FORBIDDEN_PHRASES, *plan.forbidden_phrases]:
        if phrase and _fold(phrase) in folded:
            issues.append(
                {
                    "code": "forbidden_phrase",
                    "message": f"forbidden phrase appeared: {phrase}",
                }
            )
    if _INTERNAL_RE.search(message):
        issues.append({"code": "internal_text_visible", "message": "internal text is visible"})
    if _STATE_WRITER_INTERNAL_RE.search(message):
        issues.append(
            {
                "code": "internal_state_writer_reason_visible",
                "message": "state writer internals are visible",
            }
        )
    if _PRICE_RE.search(message) and "quote" not in plan.validated_facts:
        issues.append(
            {"code": "unsupported_price_fact", "message": "price requires quote facts"}
        )
    if _REQUIREMENTS_RE.search(message) and not _has_requirements_facts(plan):
        issues.append(
            {
                "code": "unsupported_requirements_fact",
                "message": "requirements require requirements facts",
            }
        )
    if (
        plan.pending_slot
        and not plan.slot_consumed
        and plan.user_act != "answer_to_pending_slot"
        and _claims_slot_consumed(message, plan.pending_slot)
    ):
        issues.append(
            {
                "code": "slot_consumed_by_copy",
                "message": "copy claims a slot was consumed when plan says it was not",
            }
        )
    wrong_slot = _wrong_pending_slot_question(plan, message)
    if wrong_slot:
        issues.append(
            {
                "code": "wrong_pending_slot_question",
                "message": f"copy asks for {wrong_slot} while plan expects {plan.pending_slot}",
            }
        )
    if _missing_pending_slot_question(plan, message):
        issues.append(
            {
                "code": "missing_pending_slot_question",
                "message": "copy did not ask the validated pending-slot question",
            }
        )
    if _approval_promise(message):
        issues.append(
            {"code": "approval_promise", "message": "message promises approval"}
        )
    return issues


def _safe_slot_question_repair(
    plan: ValidatedResponsePlan,
    candidate: HumanResponseCandidate,
    policy_issues: list[dict[str, str]],
) -> HumanResponseCandidate | None:
    codes = {issue["code"] for issue in policy_issues}
    repair_codes = {"wrong_pending_slot_question", "missing_pending_slot_question"}
    allowed_extra_codes = {"forbidden_phrase"}
    repairable_forbidden = codes == {"forbidden_phrase"} and bool(plan.next_best_question)
    if not codes.intersection(repair_codes) and not repairable_forbidden:
        return None
    if not codes.issubset(repair_codes | allowed_extra_codes):
        return None
    if not plan.next_best_question:
        return None
    return candidate.model_copy(
        update={
            "final_message_candidate": _question_from_plan(plan.next_best_question),
            "reasoning_summary_safe": "Repaired to the validated pending-slot question.",
            "risk_flags": [
                *list(candidate.risk_flags),
                "slot_question_repaired",
            ],
        }
    )


def _safe_provider_failure_repair(
    plan: ValidatedResponsePlan,
    error: str,
) -> HumanResponseCandidate | None:
    del error
    if not plan.can_send_visible or not plan.next_best_question:
        return None
    if plan.message_goal not in {
        "ask_one_clarifying_question_for_pending_slot",
        "greet_and_resume_without_consuming_slot",
        "acknowledge_confusion_and_explain_pending_slot",
    }:
        return None
    return HumanResponseCandidate(
        final_message_candidate=_question_from_plan(plan.next_best_question),
        language="es",
        reasoning_summary_safe="Provider failed; repaired to validated pending question.",
        used_facts=list(plan.validated_facts),
        risk_flags=["human_response_provider_failed_repaired"],
    )


def human_response_json_schema() -> dict[str, Any]:
    return {
        "name": "human_response_candidate",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "final_message_candidate": {"type": "string"},
                "language": {"type": "string"},
                "reasoning_summary_safe": {"type": "string"},
                "used_facts": {"type": "array", "items": {"type": "string"}},
                "risk_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "final_message_candidate",
                "language",
                "reasoning_summary_safe",
                "used_facts",
                "risk_flags",
            ],
            "additionalProperties": False,
        },
    }


def _human_response_system_prompt() -> str:
    return "\n".join(
        [
            "You are AtendIA's HumanResponseComposer.",
            "Write only the final WhatsApp reply as a human advisor.",
            "Use only the validated facts, tool summaries, and allowed question in the plan.",
            "Do not invent prices, requirements, documents, approval, availability, or policy.",
            "Do not mention JSON, tools, traces, prompts, workflows, or internal systems.",
            "Do not use forbidden phrases.",
            "If a pending slot exists but slot_consumed=false, do not claim it was answered.",
            "If next_best_question is present, ask that pending question and do not ask "
            "about a different slot.",
            "If user_act is greeting, greet and resume softly without sounding like a form.",
            "If user_act is frustration or confusion, acknowledge and explain the pending state.",
            "If message_goal is acknowledge_future_document_without_state_write, acknowledge the "
            "future file briefly and say it is not received yet. Do not ask for a new lookup.",
            "For credit quote goals, prefer financing facts such as initial payment, installment, "
            "and term. Avoid cash/list price unless the user explicitly asked for that mode.",
            "Keep the answer short, natural, and within max_response_sentences.",
            "Return JSON only.",
        ]
    )


def _trace(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
    plan: ValidatedResponsePlan,
    candidate: HumanResponseCandidate | None,
        policy_issues: list[dict[str, str]],
        latency_ms: int,
        model_usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    pending_slot = _trace_pending_slot(plan)
    return build_trace_metadata(
        context=context,
        provider="human_response_composer",
        extra={
            **tenant_domain_trace_metadata(context),
            "architecture": [
                "context_builder",
                "semantic_interpreter",
                "tool_layer",
                "state_writer",
                "validated_response_plan_builder",
                "human_response_composer",
                "policy_validation",
            ],
            "advisor_brain": decision.model_dump(mode="json"),
            "tool_results": [result.model_dump(mode="json") for result in tool_results],
            "state_writer": {
                "accepted": state_write_result.accepted,
                "blocked": state_write_result.blocked,
                "needs_review": state_write_result.needs_review,
            },
            "policy_warnings": policy_issues,
            "model_usage": dict(model_usage or {}),
            "pending_slot": pending_slot,
            "question_slot": pending_slot,
            "validated_response_plan": plan.model_dump(mode="json"),
            "human_response_composer": {
                "candidate": candidate.model_dump(mode="json") if candidate else None,
                "policy_issues": policy_issues,
                "latency_ms": latency_ms,
            },
        },
    )


def _trace_pending_slot(plan: ValidatedResponsePlan) -> str | None:
    if not plan.pending_slot or plan.slot_consumed:
        return None
    if plan.message_goal in {
        "ask_one_clarifying_question_for_pending_slot",
        "greet_and_resume_without_consuming_slot",
        "acknowledge_confusion_and_explain_pending_slot",
    }:
        return plan.pending_slot
    return None


def _fail_closed_output(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
    plan: ValidatedResponsePlan,
    reason: str,
    error: str,
    latency_ms: int,
) -> TurnOutput:
    trace = _trace(
        context=context,
        decision=decision,
        tool_results=tool_results,
        state_write_result=state_write_result,
        plan=plan,
        candidate=None,
        policy_issues=[{"code": reason, "message": error}],
        latency_ms=latency_ms,
        model_usage=_provider_usage(None),
    )
    return TurnOutput(
        final_message=SAFE_HUMAN_REVIEW_MESSAGE,
        confidence=0.0,
        needs_human=True,
        field_updates=state_write_result.field_updates,
        lifecycle_update=state_write_result.lifecycle_update,
        risk_flags=[*list(decision.risk_flags), reason],
        knowledge_citations=context.knowledge_citations,
        trace_metadata=trace,
    )


def _claims_slot_consumed(message: str, pending_slot: str) -> bool:
    folded = _fold(message)
    if pending_slot in {"income_type", "plan", "plan_credito"}:
        return any(
            token in folded
            for token in (
                "ya valide tu tipo de ingreso",
                "ya quedo tu ingreso",
                "ya tengo tu tipo de ingreso",
                "plan validado",
            )
        )
    return False


def _wrong_pending_slot_question(
    plan: ValidatedResponsePlan,
    message: str,
) -> str | None:
    if (
        not plan.pending_slot
        or plan.slot_consumed
        or plan.message_goal
        not in {
            "ask_one_clarifying_question_for_pending_slot",
            "greet_and_resume_without_consuming_slot",
            "acknowledge_confusion_and_explain_pending_slot",
        }
    ):
        return None
    expected = _slot_family(plan.pending_slot)
    asked = _asked_slot_family(message)
    if asked and expected and asked != expected:
        return asked
    return None


def _missing_pending_slot_question(
    plan: ValidatedResponsePlan,
    message: str,
) -> bool:
    if (
        not plan.pending_slot
        or not plan.next_best_question
        or plan.user_act != "answer_to_pending_slot"
        or plan.message_goal
        not in {
            "ask_one_clarifying_question_for_pending_slot",
        }
    ):
        return False
    expected = _slot_family(plan.pending_slot)
    asked = _asked_slot_family(message)
    return asked != expected


def _question_from_plan(question: str) -> str:
    text = str(question or "").strip()
    if not text:
        return text
    if text.endswith(("?", "Â¿", "!", ".")):
        return text
    return f"{text}?"


def _asked_slot_family(message: str) -> str | None:
    folded = _fold(message)
    slot_patterns = {
        "income_type": (
            "ingreso",
            "ingresos",
            "te pagan",
            "recibes",
            "compruebas",
            "nomina",
            "recibos",
            "transferencia",
        ),
        "employment_seniority": (
            "tiempo llevas trabajando",
            "antiguedad",
            "antigüedad",
            "cuanto tiempo",
            "puesto actual",
            "empleo actual",
        ),
        "product_selection": (
            "modelo",
            "producto",
            "unidad",
            "cual quieres",
            "que quieres revisar",
            "que te interesa",
        ),
        "business_tax_status": (
            "sat",
            "rif",
            "sin comprobantes",
            "por fuera",
            "dado de alta",
            "alta fiscal",
        ),
    }
    matches = [
        family
        for family, patterns in slot_patterns.items()
        if any(pattern in folded for pattern in patterns)
    ]
    return matches[0] if len(matches) == 1 else None


def _slot_family(slot: str) -> str:
    normalized = str(slot or "").strip()
    if normalized in {"plan", "plan_credito", "income_type"}:
        return "income_type"
    if normalized in {"seniority", "employment_seniority"}:
        return "employment_seniority"
    if normalized in {"product_selection", "product", "selection"}:
        return "product_selection"
    if normalized in {"business_tax_status", "tax_status", "fiscal_status"}:
        return "business_tax_status"
    return normalized


def _response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        key: int(value)
        for key, value in {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }.items()
        if value is not None
    }


def _provider_usage(provider: Any) -> dict[str, int]:
    usage = getattr(provider, "last_usage", None)
    return dict(usage) if isinstance(usage, dict) else {}


def _approval_promise(message: str) -> bool:
    folded = _fold(message)
    return any(token in folded for token in ("aprobado", "te aprueban", "garantizado"))


def _has_requirements_facts(plan: ValidatedResponsePlan) -> bool:
    return any(
        key in plan.validated_facts
        for key in ("requirements", "requirements_checklist")
    )


def _fold(text: str) -> str:
    return (
        text.casefold()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def _latency_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


__all__ = [
    "ChatGPTHumanResponseComposerProvider",
    "HumanResponseCandidate",
    "HumanResponseComposer",
    "HumanResponseComposerProvider",
    "UnavailableHumanResponseComposerProvider",
    "build_human_response_provider",
    "human_response_json_schema",
    "validate_human_response_candidate",
]

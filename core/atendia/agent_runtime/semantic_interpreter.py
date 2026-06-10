from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    TurnContext,
)
from atendia.config import get_settings

MAX_SEMANTIC_HISTORY_MESSAGES = 20
LOW_CONFIDENCE_RISK_THRESHOLD = 0.5


class SemanticToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_payload_fixtures(cls, value: Any) -> Any:
        if isinstance(value, dict) and "payload" in value and "input" not in value:
            value = dict(value)
            value["input"] = value.pop("payload")
        return value

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self.input)


IncomeCandidate = Literal[
    "nomina_tarjeta",
    "nomina_recibos",
    "pensionado",
    "negocio_sat",
    "sin_comprobantes",
    "guardia_seguridad",
    "unknown",
]

CustomerTurnAct = Literal[
    "unknown",
    "greeting",
    "answer_to_pending_slot",
    "question",
    "correction",
    "document_upload",
    "confirmation",
    "objection",
    "confusion",
    "frustration",
    "off_topic",
    "human_request",
]


class CanonicalIncomeInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = False
    candidate: IncomeCandidate = "unknown"
    evidence: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_clarification: bool = False


class SemanticInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str | None = None
    user_act: CustomerTurnAct = "unknown"
    pending_slot_answered: str | None = None
    semantic_understanding: str = ""
    income: CanonicalIncomeInterpretation = Field(
        default_factory=CanonicalIncomeInterpretation
    )
    technical_metadata: dict[str, Any] = Field(default_factory=dict)
    proposed_fields: dict[str, Any] = Field(default_factory=dict)
    missing_field: str | None = None
    required_tools: list[SemanticToolRequest] = Field(default_factory=list)
    response_plan: str = ""
    ambiguity_reason: str | None = None
    final_message_draft: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_human: bool = False
    risk_flags: list[str] = Field(default_factory=list)


class SemanticInterpreterProvider(Protocol):
    async def interpret(self, context: TurnContext) -> SemanticInterpretation: ...


class UnavailableSemanticInterpreterProvider:
    async def interpret(self, context: TurnContext) -> SemanticInterpretation:
        del context
        return SemanticInterpretation(
            intent="needs_human_review",
            semantic_understanding=(
                "Semantic interpreter is unavailable; no deterministic keyword "
                "classification was attempted."
            ),
            response_plan="handoff_safe_no_visible_tool_facts",
            confidence=0.0,
            needs_human=True,
            risk_flags=["semantic_interpreter_unavailable"],
        )


class MockSemanticInterpreterProvider:
    def __init__(self, interpretation: SemanticInterpretation | dict[str, Any]) -> None:
        self._interpretation = (
            interpretation
            if isinstance(interpretation, SemanticInterpretation)
            else SemanticInterpretation.model_validate(interpretation)
        )
        self.calls: list[dict[str, Any]] = []

    async def interpret(self, context: TurnContext) -> SemanticInterpretation:
        self.calls.append(build_semantic_interpreter_payload(context))
        return self._interpretation


class ChatGPTSemanticInterpreterProvider:
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

    async def interpret(self, context: TurnContext) -> SemanticInterpretation:
        started = time.perf_counter()
        payload = build_semantic_interpreter_payload(context)
        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=[
                {"role": "system", "content": _semantic_system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": semantic_json_schema()},
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        interpretation = SemanticInterpretation.model_validate_json(raw)
        interpretation.technical_metadata.setdefault(
            "provider_latency_ms",
            int((time.perf_counter() - started) * 1000),
        )
        interpretation.technical_metadata.setdefault("provider", "chatgpt")
        interpretation.technical_metadata.setdefault("model", self._model)
        return interpretation


class SemanticAdvisorBrain:
    def __init__(
        self,
        interpreter: SemanticInterpreterProvider | None = None,
    ) -> None:
        self._interpreter = interpreter or build_semantic_interpreter_provider()

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        try:
            interpretation = await self._interpreter.interpret(context)
        except (ValidationError, ValueError, TypeError) as exc:
            interpretation = SemanticInterpretation(
                intent="needs_human_review",
                semantic_understanding=(
                    "Semantic interpreter returned invalid structured output."
                ),
                response_plan="handoff_safe_invalid_structured_output",
                confidence=0.0,
                needs_human=True,
                risk_flags=["semantic_interpreter_invalid_output", type(exc).__name__],
            )
        except Exception as exc:
            interpretation = SemanticInterpretation(
                intent="needs_human_review",
                semantic_understanding=(
                    "Semantic interpreter provider failed before returning structured output."
                ),
                response_plan="handoff_safe_provider_error",
                confidence=0.0,
                needs_human=True,
                risk_flags=["semantic_interpreter_provider_error", type(exc).__name__],
            )
        return advisor_decision_from_interpretation(context, interpretation)


def build_semantic_interpreter_provider() -> SemanticInterpreterProvider:
    settings = get_settings()
    if (
        settings.agent_runtime_v2_enabled
        and settings.agent_runtime_v2_model_provider == "openai"
        and settings.openai_api_key
    ):
        return ChatGPTSemanticInterpreterProvider(
            api_key=settings.openai_api_key,
            model=settings.agent_runtime_v2_model,
            timeout_s=settings.agent_runtime_v2_model_timeout_s,
        )
    return UnavailableSemanticInterpreterProvider()


def advisor_decision_from_interpretation(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> AdvisorBrainDecision:
    proposed_fields = _validated_proposed_fields(context, interpretation)
    tool_requests = [
        AdvisorBrainToolRequest(
            name=request.name,
            payload=dict(request.payload),
            reason=request.reason,
            evidence=list(request.evidence),
            required=True,
            metadata={"source": "semantic_interpreter"},
        )
        for request in _validated_tool_requests(context, interpretation)
    ]
    proposed_changes = [
        AdvisorBrainStateChange(
            target="contact_field",
            key=_canonical_field_key(context, key),
            value=value,
            reason="ChatGPT semantic interpretation proposed this field.",
            evidence=[context.inbound_text],
            confidence=interpretation.confidence,
            metadata={
                "source": "user_message",
                "semantic_interpreter": True,
                "raw_field_key": key,
            },
        )
        for key, value in proposed_fields.items()
        if str(key).strip()
        and value is not None
        and not _field_requires_tool_validation(context, key)
    ]
    missing_field = _effective_missing_field(context, interpretation)
    missing_facts = [missing_field] if missing_field else []
    risk_flags = _semantic_risk_flags(interpretation)
    answered_slot = interpretation.pending_slot_answered
    if "employment_seniority" in proposed_fields:
        answered_slot = "employment_seniority"
    return AdvisorBrainDecision(
        understanding=interpretation.semantic_understanding,
        customer_goal=interpretation.intent,
        conversation_goals=[interpretation.intent] if interpretation.intent else [],
        known_facts=dict(context.memory.salient_facts),
        missing_facts=missing_facts,
        next_best_action=(
            "ask_clarification"
            if missing_field
            else interpretation.intent or "respond"
        ),
        required_tools=tool_requests,
        proposed_state_changes=proposed_changes,
        response_plan=interpretation.response_plan
        or (
            "Use ChatGPT semantic interpretation for conversation understanding; "
            "AtendIA validates tools and state before visible output."
        ),
        confidence=interpretation.confidence,
        needs_human=interpretation.needs_human,
        risk_flags=risk_flags,
        latest_customer_act=interpretation.user_act,
        new_information_detected=bool(proposed_changes or interpretation.income.present),
        answered_slot=answered_slot,
        should_ask_question=bool(missing_field),
        question_slot=missing_field,
        metadata={
            "semantic_interpreter": True,
            "intent": interpretation.intent,
            "user_act": interpretation.user_act,
            "pending_slot_answered": answered_slot,
            "income": interpretation.income.model_dump(mode="json"),
            "technical_metadata": interpretation.technical_metadata,
            "proposed_fields": proposed_fields,
            "missing_field": missing_field,
            "response_plan": interpretation.response_plan,
            "ambiguity_reason": interpretation.ambiguity_reason,
            "final_message_draft": interpretation.final_message_draft,
        },
    )


def _semantic_risk_flags(interpretation: SemanticInterpretation) -> list[str]:
    risk_flags = list(interpretation.risk_flags)
    if (
        interpretation.confidence < LOW_CONFIDENCE_RISK_THRESHOLD
        and not interpretation.needs_human
        and "low_confidence" not in risk_flags
    ):
        risk_flags.append("low_confidence")
    return risk_flags


def _effective_missing_field(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> str | None:
    missing = _clean_missing_field(interpretation.missing_field)
    if _must_collect_seniority_before_income(context, interpretation):
        return "employment_seniority"
    if (
        interpretation.income.present
        and interpretation.income.needs_clarification
        and interpretation.income.candidate in {"unknown", "negocio_sat"}
    ):
        pending = _business_tax_status_slot(context)
        if pending:
            return pending
    if missing in {"income_type", "plan", "plan_credito"} and _current_plan(context):
        return None
    if missing in {"seniority", "employment_seniority"} and (
        _current_seniority(context) or _pending_seniority_months(context)
    ):
        return None
    if missing:
        return missing
    text = str(context.inbound_text or "").strip()
    if text and all(char in "¿?!. " for char in text):
        pending = (
            context.memory.metadata.get("pending_slot")
            or context.memory.metadata.get("question_slot")
        )
        return _clean_missing_field(pending)
    return None


def _must_collect_seniority_before_income(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> bool:
    if _current_seniority(context) or _pending_seniority_months(context):
        return False
    policy = _flow_policy(context)
    if not bool(policy.get("seniority_before_income")):
        return False
    seniority_slot = str(policy.get("seniority_slot") or "employment_seniority")
    income_slots = {"income_type", "plan", "plan_credito"}
    requested = _clean_missing_field(interpretation.missing_field)
    pending = _clean_missing_field(
        context.memory.metadata.get("pending_slot")
        or context.memory.metadata.get("question_slot")
    )
    answered = _clean_missing_field(interpretation.pending_slot_answered)
    if answered in {"seniority", seniority_slot}:
        return False
    if interpretation.income.present:
        return False
    if requested in income_slots:
        return _looks_like_credit_info_entry(context, interpretation)
    if pending in income_slots and interpretation.user_act in {
        "greeting",
        "question",
        "unknown",
    }:
        return _looks_like_credit_info_entry(context, interpretation)
    if _looks_like_credit_info_entry(context, interpretation):
        return True
    return False


def _flow_policy(context: TurnContext) -> dict[str, Any]:
    contract = context.tenant_config.tenant_domain_contract
    if isinstance(contract, dict) and isinstance(contract.get("flow_policy"), dict):
        return dict(contract["flow_policy"])
    return {}


def _looks_like_credit_info_entry(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> bool:
    inbound = _fold_text(context.inbound_text)
    short_info = {"hola", "info", "informacion", "informacion porfavor", "info porfavor"}
    if inbound in short_info:
        return True
    text = _fold_text(
        " ".join(
            [
                context.inbound_text,
                interpretation.semantic_understanding or "",
            ]
        )
    )
    if not text:
        return False
    if any(token in text for token in ("credito", "credit", "cotiza", "cotizacion")):
        return True
    return False


def _clean_missing_field(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.casefold() in {"null", "none", "missing_field", "n/a"}:
        return None
    aliases = {
        "model": "product_selection",
        "modelo": "product_selection",
        "product": "product_selection",
        "producto": "product_selection",
        "selection": "product_selection",
        "seniority": "employment_seniority",
        "antiguedad": "employment_seniority",
        "antiguedadlaboral": "employment_seniority",
        "income": "income_type",
        "ingreso": "income_type",
    }
    return aliases.get(_field_token(text), text)


def _validated_proposed_fields(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> dict[str, Any]:
    proposed = dict(interpretation.proposed_fields)
    seniority = _semantic_value(
        interpretation,
        "employment_seniority",
        "employment_seniority_months",
        "seniority",
        "antiguedad",
        "antiguedad_laboral",
    )
    if seniority is None:
        seniority = _pending_seniority_months(context)
    if seniority is None:
        seniority = _explicit_seniority_duration_months(context.inbound_text)
    seniority_months = _seniority_months(seniority)
    if seniority_months is not None:
        proposed.setdefault("employment_seniority", seniority_months)
    return {
        key: value
        for key, value in proposed.items()
        if not _field_requires_tool_validation(context, key)
    }


def _validated_tool_requests(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> list[SemanticToolRequest]:
    raw_requests = [
        *_derived_tool_requests(context, interpretation),
        *interpretation.required_tools,
    ]
    requests: list[SemanticToolRequest] = []
    seen: set[str] = set()
    for request in raw_requests:
        name = _canonical_tool_name(request.name)
        if name == "credit_plan.resolve" and _is_seniority_answer(context, interpretation):
            continue
        if (
            name == "requirements.lookup"
            and _first_value(request.input, "income_type", "income_signal", "income_candidate")
            and not _current_plan(context)
        ):
            name = "credit_plan.resolve"
        if name == "credit_plan.resolve" and _current_plan(context):
            continue
        payload = _valid_tool_payload(
            context,
            name=name,
            payload=request.input,
            interpretation=interpretation,
        )
        if payload is None:
            continue
        if name == "credit_plan.resolve" and any(
            item.name == "credit_plan.resolve" for item in requests
        ):
            continue
        key = json.dumps({"name": name, "payload": payload}, sort_keys=True, default=str)
        if key in seen:
            continue
        requests.append(request.model_copy(update={"name": name, "input": payload}))
        seen.add(key)
    return requests


def _derived_tool_requests(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> list[SemanticToolRequest]:
    requests: list[SemanticToolRequest] = []
    model_query = _semantic_value(
        interpretation,
        "model_query",
        "modelo_query",
        "model",
        "modelo",
        "product_query",
    )
    if model_query and not _current_product_display(context):
        if _looks_like_llm_model_identifier(model_query):
            model_query = None
    if not model_query and not _current_product_display(context):
        model_query = _catalog_candidate_from_tenant_sources(context, context.inbound_text)
    if model_query and not _current_product_display(context):
        requests.append(
            SemanticToolRequest(
                name="catalog.search",
                input={"query": str(model_query)},
                reason="Validate model candidate from semantic interpretation.",
                evidence=[str(model_query)],
            )
        )
    policy_query = _semantic_policy_query(
        interpretation,
        "policy_query",
        "faq_query",
        "buro_status",
        "bureau_status",
        "estado_crediticio",
        "credit_status",
    )
    if policy_query and _policy_query_has_current_turn_evidence(
        query=policy_query,
        inbound=context.inbound_text,
        interpretation=interpretation,
    ):
        requests.append(
            SemanticToolRequest(
                name="faq.lookup",
                input={"query": str(policy_query)},
                reason="Validate policy or FAQ topic from semantic interpretation.",
                evidence=[str(policy_query)],
            )
        )
    income = interpretation.income
    if (
        _answers_pending_income_slot(context, interpretation=interpretation)
        and not _current_plan(context)
    ):
        pending_slot = _current_pending_slot(context) or "income_type"
        requests.append(
            SemanticToolRequest(
                name="credit_plan.resolve",
                input={
                    "raw_answer": context.inbound_text,
                    "pending_slot": pending_slot,
                    "last_bot_question": context.memory.last_pending_question,
                    "income_candidate": (
                        income.candidate
                        if income.present and income.candidate != "unknown"
                        else None
                    ),
                    "evidence": income.evidence or context.inbound_text,
                },
                reason="Customer is answering the pending income_type slot.",
                evidence=[context.inbound_text],
            )
        )
    elif (
        income.present
        and not income.needs_clarification
        and income.candidate != "unknown"
        and not _current_plan(context)
    ):
        requests.append(
            SemanticToolRequest(
                name="credit_plan.resolve",
                input={
                    "income_candidate": income.candidate,
                    "evidence": income.evidence or context.inbound_text,
                },
                reason="Resolve credit plan from canonical income interpretation.",
                evidence=[income.evidence or context.inbound_text],
            )
        )
    intent = str(interpretation.intent or "").casefold()
    wants_requirements = "requirement" in intent or "document" in intent or "papel" in intent
    if (
        wants_requirements
        and not _is_document_future_promise(interpretation)
        and _current_plan(context)
    ):
        requests.append(
            SemanticToolRequest(
                name="requirements.lookup",
                input={"plan_credito": str(_current_plan(context))},
                reason="Resolve requirements for validated credit plan.",
                evidence=[str(_current_plan(context))],
            )
        )
    wants_quote = "quote" in intent or "cotiz" in intent or "credit" in intent
    seniority_signal = _semantic_value(
        interpretation,
        "employment_seniority",
        "seniority",
        "antiguedad",
    )
    if seniority_signal is None:
        seniority_signal = _pending_seniority_months(context)
    if (
        not wants_requirements
        and not _is_document_future_promise(interpretation)
        and not _income_needs_business_clarification(context, interpretation)
        and (
            wants_quote
            or (seniority_signal and not _current_seniority(context))
            or (
                income.present
                and not income.needs_clarification
                and income.candidate != "unknown"
                and _current_seniority(context)
            )
        )
        and _current_product_display(context)
        and (
            _current_down_payment(context)
            or (
                income.present
                and not income.needs_clarification
                and income.candidate != "unknown"
            )
        )
    ):
        quote_input: dict[str, Any] = {
            "product_query": str(_current_product_display(context)),
        }
        if _current_down_payment(context):
            quote_input["down_payment_percent"] = _current_down_payment(context)
        requests.append(
            SemanticToolRequest(
                name="quote.resolve",
                input=quote_input,
                reason="Resolve quote after model, seniority and plan are available.",
                evidence=[
                    str(_current_product_display(context)),
                    str(_current_down_payment(context) or income.candidate),
                ],
            )
        )
    return requests


def _is_seniority_answer(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> bool:
    answered = _clean_missing_field(interpretation.pending_slot_answered)
    if answered in {"seniority", "employment_seniority"}:
        return True
    if _semantic_value(
        interpretation,
        "employment_seniority",
        "employment_seniority_months",
        "seniority",
        "antiguedad",
        "antiguedad_laboral",
    ) is not None:
        return True
    if _explicit_seniority_duration_months(context.inbound_text) is not None:
        return True
    return _pending_seniority_months(context) is not None


def _income_needs_business_clarification(
    context: TurnContext,
    interpretation: SemanticInterpretation,
) -> bool:
    income = interpretation.income
    if not income.present or income.candidate in {"", "unknown"}:
        return False
    policy = _income_resolution_policy(context)
    pending_slot = str(policy.get("ambiguous_pending_slot") or "").strip()
    if not pending_slot:
        return False
    folded_candidate = _fold_text(income.candidate)
    folded_evidence = _fold_text(income.evidence or context.inbound_text)
    for rule in _as_list(policy.get("resolution_rules")):
        if not isinstance(rule, dict):
            continue
        if _fold_text(rule.get("candidate")) != folded_candidate:
            continue
        signals = rule.get("evidence_any")
        if signals and not _matches_policy_signal(folded_evidence, signals):
            return True
    return False


def _valid_tool_payload(
    context: TurnContext,
    *,
    name: str,
    payload: dict[str, Any],
    interpretation: SemanticInterpretation,
) -> dict[str, Any] | None:
    if name == "catalog.search":
        query = _first_value(payload, "query", "model", "category", "usage") or _semantic_value(
            interpretation,
            "model_query",
            "modelo_query",
            "model",
            "modelo",
            "product_query",
        )
        if _looks_like_llm_model_identifier(query):
            return None
        if _looks_like_non_answer_to_pending_slot(context.inbound_text):
            return None
        if not _is_actionable_catalog_query(query):
            return None
        return {"query": str(query).strip()} if str(query or "").strip() else None
    if name == "faq.lookup":
        query = _first_value(payload, "query", "policy_topic", "topic")
        if query is None:
            query = _semantic_policy_query(
                interpretation,
                "policy_query",
                "faq_query",
                "buro_status",
                "bureau_status",
                "estado_crediticio",
                "credit_status",
            )
        if not _policy_query_has_current_turn_evidence(
            query=query,
            inbound=context.inbound_text,
            interpretation=interpretation,
        ):
            return None
        if not _faq_payload_has_policy_intent(
            interpretation,
            query=query,
            inbound=context.inbound_text,
        ):
            return None
        return {"query": str(query).strip()} if str(query or "").strip() else None
    if name == "credit_plan.resolve":
        if interpretation.user_act in {
            "greeting",
            "question",
            "correction",
            "document_upload",
            "confirmation",
            "objection",
            "confusion",
            "frustration",
            "off_topic",
            "human_request",
        } and not _answers_pending_income_slot(
            context,
            interpretation=interpretation,
        ):
            return None
        explicit_signal = _first_value(
            payload,
            "raw_answer",
            "evidence",
            "income_signal",
            "income_type",
            "tipo_credito",
            "income_candidate",
        )
        signal = explicit_signal or _first_value(
            payload,
            "query",
            "text",
        )
        income = interpretation.income
        if signal is None and income.present:
            signal = income.evidence or income.candidate
        if signal is None and _answers_pending_income_slot(
            context,
            interpretation=interpretation,
        ):
            signal = context.inbound_text
        if not _income_payload_has_evidence(
            context,
            interpretation=interpretation,
            signal=signal,
            candidate=payload.get("income_candidate") or income.candidate,
        ):
            return None
        if (
            explicit_signal is None
            and not income.present
            and not _answers_pending_income_slot(context, interpretation=interpretation)
        ):
            return None
        if not str(signal or "").strip():
            return None
        out = {
            "raw_answer": str(payload.get("raw_answer") or context.inbound_text).strip(),
            "pending_slot": str(payload.get("pending_slot") or "").strip() or None,
            "last_bot_question": str(
                payload.get("last_bot_question") or context.memory.last_pending_question or ""
            ).strip()
            or None,
            "evidence": str(payload.get("evidence") or signal).strip(),
        }
        candidate = payload.get("income_candidate")
        if candidate or income.present:
            out["income_candidate"] = str(candidate or income.candidate).strip()
        return {key: value for key, value in out.items() if value not in (None, "")}
    if name == "requirements.lookup":
        plan = (
            _first_value(payload, "plan_id", "plan_credito", "tipo_credito")
            or _current_plan(context)
            or _first_value(payload, "query")
        )
        return {"plan_credito": str(plan).strip()} if str(plan or "").strip() else None
    if name == "document.check":
        attachments = context.metadata.get("attachments")
        if not isinstance(attachments, list) or not attachments:
            return None
        return {"attachments": attachments}
    if name == "expediente.evaluate":
        plan = (
            _first_value(payload, "plan_id", "plan_credito", "tipo_credito", "query")
            or _current_plan(context)
        )
        if not str(plan or "").strip():
            return None
        out = {"plan_credito": str(plan).strip()}
        periodicity = _first_value(payload, "payroll_periodicity", "pay_periodicity")
        if periodicity:
            out["payroll_periodicity"] = str(periodicity).strip()
        return out
    if name == "quote.resolve":
        product = (
            _first_value(payload, "product_query", "model")
            or _current_product_display(context)
        )
        down_payment = _first_value(payload, "down_payment_percent", "plan_credito")
        down_payment = down_payment if down_payment is not None else _current_down_payment(context)
        if not str(product or "").strip():
            return None
        out = {"product_query": str(product).strip()}
        if down_payment is not None:
            out["down_payment_percent"] = down_payment
        return out
    return dict(payload)


def _canonical_tool_name(name: str) -> str:
    raw = str(name or "").strip()
    if raw in {"requirements.resolve", "lookup_requirements"}:
        return "requirements.lookup"
    if raw in {"credit_plan.lookup", "plan.resolve"}:
        return "credit_plan.resolve"
    if raw in {"catalog.lookup", "search_catalog"}:
        return "catalog.search"
    if raw in {"faq.resolve", "policy.lookup"}:
        return "faq.lookup"
    if raw in {"vision.document_check", "document.classify"}:
        return "document.check"
    if raw in {"expediente.resolve", "requirements.evaluate", "document.evaluate"}:
        return "expediente.evaluate"
    return raw


def _field_requires_tool_validation(context: TurnContext, raw_key: str) -> bool:
    key = _canonical_field_key(context, str(raw_key))
    metadata = context.tenant_config.field_metadata.get(key, {})
    role = str(metadata.get("domain_role") or "")
    policy = str(metadata.get("write_policy") or "")
    return role in {"selection", "selection_metadata", "quote", "document"} or policy in {
        "tool_only",
        "auto_apply_when_catalog_match",
    }


def _semantic_value(interpretation: SemanticInterpretation, *keys: str) -> Any:
    for source in (interpretation.proposed_fields,):
        value = _first_value(source, *keys)
        if value is not None and str(value).strip():
            return value
    return None


def _looks_like_llm_model_identifier(value: Any) -> bool:
    token = str(value or "").strip().casefold()
    if not token:
        return False
    return token.startswith(("gpt-", "o1", "o3", "o4", "claude-", "gemini-"))


def _semantic_policy_query(interpretation: SemanticInterpretation, *keys: str) -> Any:
    for source in (interpretation.proposed_fields,):
        folded = {_field_token(key): (key, value) for key, value in source.items()}
        for key in keys:
            raw = folded.get(_field_token(key))
            if raw is None:
                continue
            raw_key, value = raw
            if isinstance(value, bool):
                return _policy_topic_from_key(raw_key) if value else None
            if value is not None and str(value).strip():
                return value
    return None


def _policy_topic_from_key(key: Any) -> str:
    token = _field_token(key)
    if "buro" in token or "bureau" in token:
        return "buro"
    return str(key).replace("_", " ").strip()


def _faq_payload_has_policy_intent(
    interpretation: SemanticInterpretation,
    *,
    query: Any,
    inbound: str,
) -> bool:
    text = " ".join(
        [
            str(query or ""),
            str(inbound or ""),
            str(interpretation.intent or ""),
            str(interpretation.semantic_understanding or ""),
        ]
    ).casefold()
    policy_terms = (
        "faq",
        "policy",
        "politica",
        "polÃ­tica",
        "buro",
        "burÃ³",
        "aval",
        "garantia",
        "garantÃ­a",
        "aprobar",
        "aprobacion",
        "aprobaciÃ³n",
        "liquidar",
        "penalizacion",
        "penalizaciÃ³n",
        "rechazo",
        "restriccion",
        "restricciÃ³n",
    )
    return any(term in text for term in policy_terms)


def _policy_query_has_current_turn_evidence(
    *,
    query: Any,
    inbound: str,
    interpretation: SemanticInterpretation,
) -> bool:
    folded_inbound = _fold_text(inbound)
    if not folded_inbound:
        return False
    folded_query = _fold_text(query)
    if folded_query and folded_query in folded_inbound:
        return True
    policy_terms = {
        "faq",
        "politica",
        "buro",
        "aval",
        "garantia",
        "aprobar",
        "aprobacion",
        "liquidar",
        "penalizacion",
        "rechazo",
        "restriccion",
    }
    if any(term in folded_inbound for term in policy_terms):
        return True
    intent = _fold_text(interpretation.intent)
    return any(term in intent for term in {"faq", "policy", "politica"})


def _income_payload_has_evidence(
    context: TurnContext,
    *,
    interpretation: SemanticInterpretation | None = None,
    signal: Any,
    candidate: Any,
) -> bool:
    if _answers_pending_income_slot(context, interpretation=interpretation):
        return True
    folded_signal = _fold_text(signal)
    folded_inbound = _fold_text(context.inbound_text)
    if folded_signal and folded_signal in folded_inbound:
        return True
    policy = _income_resolution_policy(context)
    for key in ("ambiguous_signals",):
        if _matches_policy_signal(folded_signal, policy.get(key)):
            return True
    for rule in _as_list(policy.get("resolution_rules")):
        if not isinstance(rule, dict):
            continue
        if _matches_policy_signal(folded_signal, rule.get("evidence_any")):
            return True
    return False


def _income_resolution_policy(context: TurnContext) -> dict[str, Any]:
    contract = context.tenant_config.tenant_domain_contract
    if isinstance(contract, dict) and isinstance(contract.get("income_resolution_policy"), dict):
        return dict(contract["income_resolution_policy"])
    return {}


def _matches_policy_signal(folded_text: str, signals: Any) -> bool:
    if not folded_text:
        return False
    for signal in _as_list(signals):
        folded_signal = _fold_text(signal)
        if folded_signal and (folded_signal == folded_text or folded_signal in folded_text):
            return True
    return False


def _is_document_future_promise(interpretation: SemanticInterpretation) -> bool:
    text = " ".join(
        [
            str(interpretation.intent or ""),
            str(interpretation.semantic_understanding or ""),
            str(interpretation.response_plan or ""),
        ]
    ).casefold()
    return any(
        token in text
        for token in (
            "document_future_promise",
            "will_send_document",
            "promesa_documento",
            "send_document_later",
            "mandar ine despues",
            "mandar ine después",
        )
    )


def _first_value(source: dict[str, Any], *keys: str) -> Any:
    folded = {_field_token(key): value for key, value in source.items()}
    for key in keys:
        value = folded.get(_field_token(key))
        if value is not None:
            return value
    return None


def _current_product_display(context: TurnContext) -> str | None:
    value = _current_value(context, "product_selection")
    if isinstance(value, dict):
        return str(value.get("display_name") or value.get("sku") or "").strip() or None
    quote = context.memory.last_quote_snapshot
    if isinstance(quote, dict):
        product = quote.get("product")
        if isinstance(product, dict):
            display = str(product.get("display_name") or product.get("sku") or "").strip()
            if display:
                return display
    return str(value or "").strip() or None


def _current_plan(context: TurnContext) -> str | None:
    value = _current_value(context, "plan_selection")
    if not value and isinstance(context.memory.last_quote_snapshot, dict):
        value = (
            context.memory.last_quote_snapshot.get("plan_name")
            or context.memory.last_quote_snapshot.get("plan_code")
        )
    return str(value or "").strip() or None


def _current_down_payment(context: TurnContext) -> Any:
    value = _current_value(context, "down_payment_percent")
    if value is not None:
        return value
    quote = context.memory.last_quote_snapshot
    if isinstance(quote, dict):
        plan_name = str(quote.get("plan_name") or quote.get("plan_code") or "")
        match = re.search(r"(\d+)", plan_name)
        if match:
            return int(match.group(1))
    return None


def _current_seniority(context: TurnContext) -> Any:
    return _current_value(context, "employment_seniority")


def _pending_seniority_months(context: TurnContext) -> int | None:
    pending = _current_pending_slot(context)
    if pending not in {"seniority", "employment_seniority"}:
        return None
    return _seniority_months(context.inbound_text)


def _explicit_seniority_duration_months(text: Any) -> int | None:
    raw = str(text or "")
    folded = unicodedata.normalize("NFKD", raw.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    match = re.search(
        r"\b(\d{1,2})\s*(mes|meses|month|months|ano|anos|a\W{1,3}os|year|years)\b",
        folded,
    )
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None
    if unit in {"ano", "anos", "year", "years"} or (
        unit.startswith("a") and unit.endswith("os")
    ):
        return amount * 12
    return amount


def _answers_pending_income_slot(
    context: TurnContext,
    *,
    interpretation: SemanticInterpretation | None = None,
) -> bool:
    pending = _clean_missing_field(
        context.memory.metadata.get("pending_slot")
        or context.memory.metadata.get("question_slot")
    )
    if pending not in _income_pending_slots(context):
        return False
    text = str(context.inbound_text or "").strip()
    if not text:
        return False
    if pending == _business_tax_status_slot(context):
        return _business_tax_status_answer_has_evidence(context, interpretation)
    if interpretation is not None:
        if interpretation.user_act == "unknown":
            return not _looks_like_non_answer_to_pending_slot(text)
        if not _allows_pending_slot_consumption(interpretation):
            return False
        answered = _clean_missing_field(interpretation.pending_slot_answered)
        if answered in _income_pending_slots(context):
            return True
        income = interpretation.income
        return bool(
            income.present
            and not income.needs_clarification
            and str(income.evidence or "").strip()
        )
    return not all(char in "Â¿?!. " for char in text)


def _current_pending_slot(context: TurnContext) -> str | None:
    return _clean_missing_field(
        context.memory.metadata.get("pending_slot")
        or context.memory.metadata.get("question_slot")
    )


def _looks_like_non_answer_to_pending_slot(text: str) -> bool:
    folded = _fold_text(text)
    if not folded:
        return True
    if all(char in "¿?!. " for char in text):
        return True
    return folded in {
        "hola",
        "buen dia",
        "buenos dias",
        "buenas",
        "buenas tardes",
        "buenas noches",
        "hey",
        "oye",
        "entonces",
        "dime",
        "ya te dije",
        "ya dije",
    }


def _allows_pending_slot_consumption(interpretation: SemanticInterpretation) -> bool:
    if interpretation.user_act == "answer_to_pending_slot":
        return True
    if interpretation.user_act in {
        "greeting",
        "question",
        "correction",
        "document_upload",
        "confirmation",
        "objection",
        "confusion",
        "frustration",
        "off_topic",
        "human_request",
    }:
        return False
    return True


def _income_pending_slots(context: TurnContext) -> set[str]:
    slots = {"income_type", "plan", "plan_credito"}
    contract = context.tenant_config.tenant_domain_contract
    flow_policy = contract.get("flow_policy") if isinstance(contract, dict) else None
    if isinstance(flow_policy, dict):
        ambiguous_slot = str(flow_policy.get("business_activity_ambiguous_slot") or "").strip()
        if ambiguous_slot:
            slots.add(_clean_missing_field(ambiguous_slot))
    return slots


def _business_tax_status_slot(context: TurnContext) -> str | None:
    policy = _income_resolution_policy(context)
    slot = _clean_missing_field(policy.get("ambiguous_pending_slot"))
    if slot:
        return slot
    contract = context.tenant_config.tenant_domain_contract
    flow_policy = contract.get("flow_policy") if isinstance(contract, dict) else None
    if isinstance(flow_policy, dict):
        return _clean_missing_field(flow_policy.get("business_activity_ambiguous_slot"))
    return None


def _business_tax_status_answer_has_evidence(
    context: TurnContext,
    interpretation: SemanticInterpretation | None,
) -> bool:
    policy = _income_resolution_policy(context)
    texts = [context.inbound_text]
    if interpretation is not None:
        texts.extend(
            [
                interpretation.income.evidence,
                interpretation.income.candidate,
                interpretation.semantic_understanding,
            ]
        )
    folded_text = _fold_text(" ".join(str(item or "") for item in texts))
    for rule in _as_list(policy.get("resolution_rules")):
        if not isinstance(rule, dict):
            continue
        if _matches_policy_signal(folded_text, rule.get("evidence_any")):
            return True
    return False


def _catalog_candidate_from_tenant_sources(context: TurnContext, inbound: str) -> str | None:
    folded_inbound = _fold_text(inbound)
    if not folded_inbound:
        return None
    for source in context.tenant_config.knowledge_sources:
        if "catalog" not in str(source).casefold():
            continue
        path = Path(str(source))
        if not path.exists():
            path = Path.cwd().parent / str(source)
        if not path.exists():
            path = Path.cwd() / str(source)
        if not path.exists():
            continue
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidate = _catalog_candidate_from_value(catalog, folded_inbound)
        if candidate:
            return candidate
    return None


def _is_actionable_catalog_query(query: Any) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    return not all(char in "Â¿?!. " for char in text)


def _catalog_candidate_from_value(
    value: Any,
    folded_inbound: str,
    *,
    parent_key: str = "",
) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in {"modelo", "display_name", "nombre", "sku"}:
                candidate = _model_candidate(str(nested), folded_inbound)
                if candidate:
                    return candidate
            if str(key) in {"alias", "aliases", "alias_normalizados"}:
                candidate = _alias_candidate(nested, folded_inbound)
                if candidate:
                    return candidate
            if isinstance(nested, dict | list):
                candidate = _catalog_candidate_from_value(
                    nested,
                    folded_inbound,
                    parent_key=str(key),
                )
                if candidate:
                    return candidate
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and parent_key in {"modelos", "models"}:
                candidate = _model_candidate(item, folded_inbound)
                if candidate:
                    return candidate
            if isinstance(item, dict | list):
                candidate = _catalog_candidate_from_value(
                    item,
                    folded_inbound,
                    parent_key=parent_key,
                )
                if candidate:
                    return candidate
    return None


def _alias_candidate(value: Any, folded_inbound: str) -> str | None:
    for item in _as_list(value):
        candidate = _model_candidate(str(item), folded_inbound)
        if candidate:
            return candidate
    return None


def _model_candidate(value: str, folded_inbound: str) -> str | None:
    folded_value = _fold_text(value)
    folded_query = _strip_leading_article(folded_inbound)
    if not folded_value:
        return None
    if folded_query == folded_value or folded_query in folded_value:
        return value
    if any(token in folded_query for token in _distinct_catalog_tokens(value)):
        return value
    return None


def _strip_leading_article(folded_text: str) -> str:
    for article in ("la", "el", "una", "un"):
        if folded_text.startswith(article) and len(folded_text) > len(article) + 2:
            return folded_text[len(article) :]
    return folded_text


def _distinct_catalog_tokens(value: str) -> list[str]:
    ignored = {"cc", "modelo", "moto", "motocicleta", "elite"}
    tokens = []
    for token in re.findall(r"[A-Za-z0-9]+", value.casefold()):
        folded = _fold_text(token)
        if len(folded) >= 4 and folded not in ignored and not folded.isdigit():
            tokens.append(folded)
    return tokens


def _current_value(context: TurnContext, key: str) -> Any:
    if key in context.customer.attrs:
        return context.customer.attrs.get(key)
    if key in context.memory.salient_facts:
        return context.memory.salient_facts.get(key)
    return None


def _seniority_months(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = _field_token(value).replace("ñ", "n")
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    if any(token in text for token in ("ano", "anos", "year", "years")):
        return amount * 12
    return amount


def build_semantic_interpreter_payload(context: TurnContext) -> dict[str, Any]:
    return {
        "tenant_id": context.tenant_id,
        "conversation_id": context.conversation_id,
        "current_message": context.inbound_text,
        "last_20_messages": [
            {
                "role": message.role,
                "text": message.text,
                "sent_at": message.sent_at,
            }
            for message in context.messages[-MAX_SEMANTIC_HISTORY_MESSAGES:]
        ],
        "validated_contact_state": {
            "customer_attrs": context.customer.attrs,
            "salient_facts": context.memory.salient_facts,
            "lifecycle": context.lifecycle.model_dump(mode="json"),
            "validated_product": _current_product_display(context),
            "validated_plan": _current_plan(context),
            "validated_down_payment_percent": _current_down_payment(context),
            "validated_seniority": _current_seniority(context),
        },
        "last_bot_question": context.memory.last_pending_question,
        "pending_slot": context.memory.metadata.get("pending_slot")
        or context.memory.metadata.get("question_slot")
        or context.memory.last_pending_question,
        "knowledge": [
            citation.model_dump(mode="json") for citation in context.knowledge_citations
        ],
            "tools_available": sorted(context.tenant_config.tool_metadata),
            "hard_data_restrictions": {
                "catalog": "Models and prices require catalog.search.",
                "quote": "Prices/payments require quote.resolve.",
                "requirements": "Documents require requirements.lookup.",
                "income": "Income-to-plan mapping requires credit_plan.resolve.",
            "faq": "Policies require faq.lookup.",
            "state": "StateWriter may block any field without sufficient evidence.",
        },
        "prompt_master_rules": {
            "single_question": True,
            "no_invented_prices_requirements_or_approval": True,
            "short_whatsapp_style": True,
            "ambiguous_language_requires_clarification": True,
            "tool_payload_contracts": {
                "catalog.search": "Use input {'query': model_or_category}.",
                "requirements.lookup": (
                    "Use only when plan/down_payment is already validated. Input "
                    "must be {'plan_credito': validated_plan} or {'plan_id': id}."
                ),
                "credit_plan.resolve": (
                    "Use input {'income_candidate': canonical_enum, "
                    "'evidence': customer_income_words} when income.present=true."
                ),
                "faq.lookup": "Use input {'query': policy_or_faq_topic}.",
                "quote.resolve": (
                    "Use only after catalog model and requirements plan are known; "
                    "input must include model/product_query and down_payment_percent."
                ),
            },
            "hard_fields_tool_only": [
                "product_selection",
                "product_catalog_id",
                "plan_selection",
                "down_payment_percent",
                "quote_snapshot_id",
                "payment_amount",
                "cash_price",
                "requirements_checklist",
            ],
        },
    }


def semantic_json_schema() -> dict[str, Any]:
    object_schema = {"type": "object"}
    income_schema = {
        "type": "object",
        "properties": {
            "present": {"type": "boolean"},
            "candidate": {
                "type": "string",
                "enum": [
                    "nomina_tarjeta",
                    "nomina_recibos",
                    "pensionado",
                    "negocio_sat",
                    "sin_comprobantes",
                    "guardia_seguridad",
                    "unknown",
                ],
            },
            "evidence": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_clarification": {"type": "boolean"},
        },
        "required": [
            "present",
            "candidate",
            "evidence",
            "confidence",
            "needs_clarification",
        ],
        "additionalProperties": False,
    }
    tool_request = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "input": object_schema,
            "reason": {"type": ["string", "null"]},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "input", "reason", "evidence"],
        "additionalProperties": False,
    }
    return {
        "name": "semantic_interpretation",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": ["string", "null"]},
                "user_act": {
                    "type": "string",
                    "enum": [
                        "unknown",
                        "greeting",
                        "answer_to_pending_slot",
                        "question",
                        "correction",
                        "document_upload",
                        "confirmation",
                        "objection",
                        "confusion",
                        "frustration",
                        "off_topic",
                        "human_request",
                    ],
                },
                "pending_slot_answered": {"type": ["string", "null"]},
                "semantic_understanding": {"type": "string"},
                "income": income_schema,
                "proposed_fields": object_schema,
                "missing_field": {"type": ["string", "null"]},
                "required_tools": {"type": "array", "items": tool_request},
                "response_plan": {"type": "string"},
                "ambiguity_reason": {"type": ["string", "null"]},
                "final_message_draft": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "needs_human": {"type": "boolean"},
                "risk_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "intent",
                "user_act",
                "pending_slot_answered",
                "semantic_understanding",
                "income",
                "proposed_fields",
                "missing_field",
                "required_tools",
                "response_plan",
                "ambiguity_reason",
                "final_message_draft",
                "confidence",
                "needs_human",
                "risk_flags",
            ],
            "additionalProperties": False,
        },
    }


def _semantic_system_prompt() -> str:
    return "\n".join(
        [
            "You are ChatGPT acting only as AtendIA's semantic conversation interpreter.",
            (
                "Interpret tenant-scoped Spanish WhatsApp conversations, "
                "but return structured JSON only."
            ),
            "Do not validate hard facts yourself. Ask tools for facts.",
            "Do not use keyword routing or rigid one-word mappings.",
            "Do not return free-form semantic_signals.",
            "Return only the JSON schema. No prose outside JSON.",
            "Use context, last messages, pending slot, and validated contact state.",
            (
                "Always classify the latest customer turn as user_act using exactly "
                "one of: greeting, answer_to_pending_slot, question, correction, "
                "document_upload, confirmation, objection, confusion, frustration, "
                "off_topic, human_request, unknown."
            ),
            (
                "A pending slot is consumed only when user_act is "
                "answer_to_pending_slot. A greeting, confusion, frustration, or "
                "side question must not be treated as an answer to the pending slot."
            ),
            (
                "If validated_plan and validated_down_payment_percent are present, "
                "income_type and plan are already resolved; do not mark them missing."
            ),
            "If ambiguous, set missing_field and draft one natural clarification.",
            "Do not return customer-visible final copy.",
            "Do not invent prices, documents, policies, approval, or availability.",
            "Use Spanish for semantic_understanding, response_plan, and ambiguity_reason.",
            (
                "missing_field must be a stable machine key like income_type, "
                "model, plan, or seniority."
            ),
            "Do not put hard tool-owned fields in proposed_fields.",
            (
                "Always fill income as a canonical object. Use candidate exactly "
                "one of: nomina_tarjeta, nomina_recibos, pensionado, negocio_sat, "
                "sin_comprobantes, guardia_seguridad, unknown."
            ),
            (
                "If pending_slot is income_type and the latest customer message "
                "answers how they receive income, set pending_slot_answered="
                "income_type and income.present=true."
            ),
            "For a model mention, request catalog.search with input {'query': '<model>'}.",
            "For bureau/policy questions, request faq.lookup with input {'query': '<topic>'}.",
            (
                "If current_message or recent context mentions buro/buró, "
                "request faq.lookup with input {'query': 'buro'}."
            ),
            (
                "For income-to-plan, prefer credit_plan.resolve with input "
                "{'income_candidate': '<canonical_candidate>', 'evidence': '<customer words>'}."
            ),
            "For documents, request requirements.lookup only when plan/down_payment is known.",
            "If missing_field is set, do not request tools that need that missing value.",
            "A tool may be requested when it can resolve the missing field from current text.",
            (
                "For quote.resolve, wait until both catalog model and "
                "plan/down_payment_percent are known."
            ),
            (
                "If the latest customer message is only '?' or punctuation, explain "
                "the current pending slot from context instead of changing topics."
            ),
            (
                "If the customer promises to send an ID or file later, use intent "
                "document_future_promise, no required_tools, no proposed_fields, "
                "missing_field null, and response_plan to acknowledge future receipt."
            ),
            (
                "If a credit quote lacks income_type/plan, ask one question "
                "about how they receive income."
            ),
            (
                "Never ask whether the customer wants requirements when they "
                "asked for a quote; ask missing data."
            ),
            (
                "'trabajo' alone is only a semantic signal. Decide from context "
                "or ask one clarification."
            ),
            "'tengo 2 anos trabajando' or 'tengo 2 anos' after an income question means seniority.",
        ]
    )


def _canonical_field_key(context: TurnContext, raw_key: str) -> str:
    if raw_key in context.tenant_config.field_metadata:
        return raw_key
    token = _field_token(raw_key)
    for key, metadata in context.tenant_config.field_metadata.items():
        aliases = [key, metadata.get("label"), *list(metadata.get("aliases") or [])]
        if token in {_field_token(alias) for alias in aliases if alias}:
            return str(key)
    return raw_key


def _field_token(value: Any) -> str:
    return str(value or "").casefold().replace("_", "").replace("-", "").replace(" ", "")


def _fold_text(value: Any) -> str:
    return _field_token(str(value or "").replace("%", ""))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set | frozenset):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


__all__ = [
    "MAX_SEMANTIC_HISTORY_MESSAGES",
    "ChatGPTSemanticInterpreterProvider",
    "MockSemanticInterpreterProvider",
    "SemanticAdvisorBrain",
    "SemanticInterpretation",
    "SemanticInterpreterProvider",
    "SemanticToolRequest",
    "UnavailableSemanticInterpreterProvider",
    "advisor_decision_from_interpretation",
    "build_semantic_interpreter_payload",
    "semantic_json_schema",
]

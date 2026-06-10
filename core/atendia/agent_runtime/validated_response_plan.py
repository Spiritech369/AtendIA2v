from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ToolExecutionResult,
    TurnContext,
)
from atendia.agent_runtime.state_writer import StateWriteResult

DEFAULT_FORBIDDEN_PHRASES = [
    "Si se puede revisar",
    "Sí se puede revisar",
    "Dime que dato quieres revisar",
    "Dime qué dato quieres revisar",
    "reviso el contexto",
    "te doy continuidad",
    "siguiente paso con el contexto actual",
    "Tomo tu mensaje",
    "Si necesitas más información",
    "Si necesitas mas informacion",
    "estoy aquí para ayudarte",
    "estoy aqui para ayudarte",
    "aquí estoy",
    "aqui estoy",
    "en qué puedo ayudarte hoy",
    "en que puedo ayudarte hoy",
    "tu solicitud está siendo revisada",
    "tu solicitud esta siendo revisada",
    "te responderán pronto",
    "te responderan pronto",
]


class ValidatedResponsePlan(BaseModel):
    """Validated facts and allowed response intent for visible human composition."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    agent_id: str | None = None
    conversation_id: str
    user_act: str
    intent: str | None = None
    pending_slot: str | None = None
    slot_consumed: bool = False
    message_goal: str
    validated_facts: dict[str, Any] = Field(default_factory=dict)
    tool_results_summary: list[dict[str, Any]] = Field(default_factory=list)
    state_writes_summary: dict[str, Any] = Field(default_factory=dict)
    next_best_question: str | None = None
    clarification_question: str | None = None
    forbidden_phrases: list[str] = Field(default_factory=lambda: list(DEFAULT_FORBIDDEN_PHRASES))
    required_sources: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    style_constraints: dict[str, Any] = Field(default_factory=dict)
    max_response_sentences: int = 2
    can_send_visible: bool = True
    failure_reason: str | None = None


class ValidatedResponsePlanBuilder:
    def build(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]] | None = None,
    ) -> ValidatedResponsePlan:
        user_act = _customer_turn_act(decision)
        pending_slot = _pending_slot(context, decision, tool_results, state_write_result)
        slot_consumed = _slot_consumed(decision, pending_slot)
        validated_facts = _validated_facts(context, tool_results, state_write_result)
        required_tools = [
            result.tool_name for result in tool_results if result.status == "succeeded"
        ]
        can_send_visible = not any(
            result.status in {"failed", "blocked"} for result in tool_results
        )
        message_goal = _message_goal(
            user_act=user_act,
            pending_slot=pending_slot,
            slot_consumed=slot_consumed,
            validated_facts=validated_facts,
            decision=decision,
        )
        next_question = _next_question(
            user_act=user_act,
            pending_slot=pending_slot,
            slot_consumed=slot_consumed,
            decision=decision,
            tool_results=tool_results,
        )
        return ValidatedResponsePlan(
            tenant_id=context.tenant_id,
            agent_id=context.active_agent.id if context.active_agent else None,
            conversation_id=context.conversation_id,
            user_act=user_act,
            intent=decision.customer_goal,
            pending_slot=pending_slot,
            slot_consumed=slot_consumed,
            message_goal=message_goal,
            validated_facts=validated_facts,
            tool_results_summary=_tool_results_summary(tool_results),
            state_writes_summary={
                "accepted": list(state_write_result.accepted),
                "blocked": list(state_write_result.blocked),
                "needs_review": list(state_write_result.needs_review),
                "accepted_count": state_write_result.summary.get("accepted_count", 0),
                "blocked_count": state_write_result.summary.get("blocked_count", 0),
            },
            next_best_question=next_question,
            clarification_question=_clarification_question(tool_results),
            required_sources=_required_sources(tool_results),
            required_tools=required_tools,
            risk_flags=[
                *list(decision.risk_flags),
                *[str(item.get("code")) for item in policy_warnings or [] if item.get("code")],
            ],
            style_constraints=_style_constraints(context),
            max_response_sentences=int(
                _style_constraints(context).get("max_sentences")
                or context.tenant_config.metadata.get("max_response_sentences")
                or 2
            ),
            can_send_visible=can_send_visible,
            failure_reason=None if can_send_visible else "tool_failed_or_blocked",
        )


def _customer_turn_act(decision: AdvisorBrainDecision) -> str:
    return str(
        decision.latest_customer_act
        or decision.metadata.get("user_act")
        or "unknown"
    ).strip() or "unknown"


def _pending_slot(
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
) -> str | None:
    flow_transition = _pending_slot_after_state_write(context, state_write_result)
    if flow_transition:
        return flow_transition
    for result in tool_results:
        if result.tool_name == "credit_plan.resolve" and result.status == "succeeded":
            if result.data.get("needs_clarification"):
                pending = result.data.get("pending_slot")
                return str(pending) if pending else "income_type"
            if not _current_value(context, state_write_result, "employment_seniority"):
                return "employment_seniority"
            if not _current_value(context, state_write_result, "product_selection"):
                return "product_selection"
            pending = result.data.get("pending_slot")
            if pending:
                return str(pending)
    return str(
        decision.question_slot
        or decision.metadata.get("missing_field")
        or context.memory.metadata.get("pending_slot")
        or ""
    ).strip() or None


def _pending_slot_after_state_write(
    context: TurnContext,
    state_write_result: StateWriteResult,
) -> str | None:
    flow_policy = _flow_policy(context)
    seniority_slot = str(flow_policy.get("seniority_slot") or "employment_seniority")
    income_slot = str(flow_policy.get("income_slot") or "income_type")
    if _has_accepted_field(state_write_result, seniority_slot):
        if _current_value(context, state_write_result, income_slot):
            return None
        return income_slot
    if not _has_accepted_selection(state_write_result):
        return None
    if (
        flow_policy.get("seniority_before_income") is True
        and not _current_value(context, state_write_result, seniority_slot)
    ):
        return seniority_slot
    if not _current_value(context, state_write_result, income_slot):
        return income_slot
    return None


def _slot_consumed(decision: AdvisorBrainDecision, pending_slot: str | None) -> bool:
    answered = str(decision.answered_slot or decision.metadata.get("pending_slot_answered") or "")
    income = decision.metadata.get("income")
    if (
        pending_slot == "business_tax_status"
        and isinstance(income, dict)
        and income.get("needs_clarification")
    ):
        return False
    return bool(pending_slot and answered and answered == pending_slot)


def _validated_facts(
    context: TurnContext,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for key in (
        "product_selection",
        "plan_selection",
        "down_payment_percent",
        "employment_seniority",
        "requirements_checklist",
        "Doc_Completos",
        "requirements_complete",
    ):
        value = _current_value(context, state_write_result, key)
        if value is not None:
            facts[key] = value
    for result in tool_results:
        if result.status != "succeeded":
            continue
        if result.tool_name == "catalog.search":
            facts["catalog"] = result.data
        elif result.tool_name == "credit_plan.resolve":
            facts["credit_plan"] = result.data
        elif result.tool_name == "quote.resolve":
            facts["quote"] = result.data
        elif result.tool_name == "requirements.lookup":
            facts["requirements"] = result.data
        elif result.tool_name in {"faq.lookup", "policy.lookup"}:
            facts["policy"] = result.data
        elif result.tool_name in {"document.check", "expediente.evaluate"}:
            facts[result.tool_name.replace(".", "_")] = result.data
    if context.memory.last_quote_snapshot and "quote" not in facts:
        facts["last_quote_snapshot"] = context.memory.last_quote_snapshot
    return facts


def _tool_results_summary(tool_results: list[ToolExecutionResult]) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": result.tool_name,
            "status": result.status,
            "data_keys": sorted(result.data.keys()),
            "error": result.error,
        }
        for result in tool_results
    ]


def _message_goal(
    *,
    user_act: str,
    pending_slot: str | None,
    slot_consumed: bool,
    validated_facts: dict[str, Any],
    decision: AdvisorBrainDecision,
) -> str:
    if "quote" in validated_facts:
        return "explain_validated_quote"
    if "requirements" in validated_facts:
        return "explain_validated_requirements"
    if "expediente_evaluate" in validated_facts:
        return "explain_validated_document_status"
    if decision.customer_goal == "document_future_promise" or user_act == "document_upload":
        return "acknowledge_future_document_without_state_write"
    credit_plan = validated_facts.get("credit_plan")
    if isinstance(credit_plan, dict) and credit_plan.get("needs_clarification"):
        return "ask_one_clarifying_question_for_pending_slot"
    if pending_slot in {"seniority", "employment_seniority"} and not slot_consumed:
        return "ask_one_clarifying_question_for_pending_slot"
    if user_act == "greeting" and pending_slot and not slot_consumed:
        return "greet_and_resume_without_consuming_slot"
    if user_act in {"confusion", "frustration"} and pending_slot and not slot_consumed:
        return "acknowledge_confusion_and_explain_pending_slot"
    if pending_slot and not slot_consumed:
        return "ask_one_clarifying_question_for_pending_slot"
    if decision.needs_human:
        return "handoff_for_human_review"
    return "respond_from_validated_context"


def _next_question(
    *,
    user_act: str,
    pending_slot: str | None,
    slot_consumed: bool,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
) -> str | None:
    clarification = _clarification_question(tool_results)
    if clarification:
        return clarification
    income = decision.metadata.get("income")
    if isinstance(income, dict) and income.get("needs_clarification"):
        candidate = str(income.get("candidate") or "")
        if candidate == "negocio_sat":
            return _pending_slot_label("business_tax_status")
    if not pending_slot or slot_consumed:
        return None
    if user_act == "greeting":
        return _pending_slot_label(pending_slot)
    if user_act in {"confusion", "frustration"}:
        return _pending_slot_label(pending_slot)
    if decision.should_ask_question:
        return _pending_slot_label(pending_slot)
    return _pending_slot_label(pending_slot)


def _clarification_question(tool_results: list[ToolExecutionResult]) -> str | None:
    for result in tool_results:
        if result.tool_name != "credit_plan.resolve" or result.status != "succeeded":
            continue
        clarification = result.data.get("clarification")
        if isinstance(clarification, dict):
            question = clarification.get("question") or clarification.get("message")
            if question:
                return str(question)
        if result.data.get("needs_clarification") and result.data.get("pending_slot"):
            return _pending_slot_label(str(result.data["pending_slot"]))
    return None


def _pending_slot_label(slot: str) -> str:
    labels = {
        "income_type": "como recibes tus ingresos",
        "plan": "como compruebas tus ingresos",
        "plan_credito": "como compruebas tus ingresos",
        "business_tax_status": "si tienes SAT/RIF o si seria sin comprobantes",
        "seniority": "cuanto tiempo llevas trabajando",
        "employment_seniority": "cuanto tiempo llevas trabajando",
        "product_selection": "que modelo de moto quieres revisar",
    }
    return labels.get(slot, slot.replace("_", " "))


def _required_sources(tool_results: list[ToolExecutionResult]) -> list[str]:
    sources: list[str] = []
    for result in tool_results:
        if result.status != "succeeded":
            continue
        source = result.data.get("source") or result.data.get("source_id") or result.tool_name
        sources.append(str(source))
    return sorted(set(sources))


def _style_constraints(context: TurnContext) -> dict[str, Any]:
    voice = {}
    if context.active_agent:
        voice.update(context.active_agent.voice)
        if context.active_agent.tone:
            voice.setdefault("tone", context.active_agent.tone)
        if context.active_agent.role:
            voice.setdefault("role", context.active_agent.role)
    voice.update(context.tenant_config.default_voice)
    return {
        "persona": voice.get("persona") or voice.get("name") or "asesor",
        "tone": voice.get("tone") or "WhatsApp humano, breve, asesor",
        "max_sentences": int(voice.get("max_sentences") or 2),
    }


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


def _flow_policy(context: TurnContext) -> dict[str, Any]:
    contract = context.tenant_config.tenant_domain_contract
    if isinstance(contract, dict) and isinstance(contract.get("flow_policy"), dict):
        return dict(contract["flow_policy"])
    metadata_contract = context.tenant_config.metadata.get("tenant_domain_contract")
    if isinstance(metadata_contract, dict) and isinstance(
        metadata_contract.get("flow_policy"), dict
    ):
        return dict(metadata_contract["flow_policy"])
    return {}


def _has_accepted_field(
    state_write_result: StateWriteResult,
    field_key: str,
) -> bool:
    target = str(field_key or "")
    if not target:
        return False
    for update in state_write_result.field_updates:
        if update.field_key == target:
            return True
    for item in state_write_result.accepted:
        if not isinstance(item, dict):
            continue
        if item.get("field") == target or item.get("key") == target:
            return True
    return False


def _has_accepted_selection(state_write_result: StateWriteResult) -> bool:
    for update in state_write_result.field_updates:
        if update.field_key == "product_selection":
            return True
    for item in state_write_result.accepted:
        if not isinstance(item, dict):
            continue
        if item.get("field") == "product_selection" or item.get("key") == "product_selection":
            return True
        if item.get("domain_role") == "selection":
            return True
    return False

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atendia.agent_runtime.canonical import CanonicalProductReference, QuoteSnapshot
from atendia.agent_runtime.mandatory_tools import MandatoryToolGuard
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    CustomerContext,
    LifecycleContext,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import (
    DeterministicStateWriter,
    StateWriteResult,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)
from atendia.agent_runtime.tracing import build_trace_metadata
from atendia.agent_runtime.universal_turn_trace import attach_universal_turn_trace

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"
TENANT_ID = "6ad78236-1fc9-467a-858d-90d248d57ee5"
AGENT_ID = "c169deec-226d-55b7-bd07-270f339e75a6"
CONVERSATION_ID = "dinamo-shadow-conversation-1"
CONTACT_ID = "dinamo-shadow-contact-1"


@dataclass(frozen=True)
class ShadowTurn:
    context: TurnContext
    decision: AdvisorBrainDecision
    tool_results: list[ToolExecutionResult]
    state_write_result: StateWriteResult
    output: TurnOutput
    trace: dict[str, Any]


def _fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "dinamo_motos_nl_shadow.json").read_text())


def _tenant_config(raw: dict[str, Any] | None = None) -> TenantRuntimeConfigContext:
    contract = raw or _fixture()
    result = load_tenant_domain_contract(
        contract,
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
    )
    return apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)


def _context(
    *,
    turn_number: int,
    inbound_text: str,
    memory: dict[str, Any] | None = None,
    lifecycle_stage: str = "nuevo",
    metadata: dict[str, Any] | None = None,
) -> TurnContext:
    return TurnContext(
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        inbound_text=inbound_text,
        customer=CustomerContext(id=CONTACT_ID),
        lifecycle=LifecycleContext(
            stage=lifecycle_stage,
            pipeline_id="dinamo_vehicle_credit_shadow",
        ),
        tenant_config=_tenant_config(),
        active_agent=ActiveAgentContext(
            id=AGENT_ID,
            name="Francisco de Dinamo NL",
            behavior_mode="shadow",
        ),
        memory={"salient_facts": dict(memory or {})},
        metadata={
            "turn_id": f"dinamo-shadow-turn-{turn_number}",
            "turn_number": turn_number,
            "message_id": f"msg-{turn_number}",
            "runtime_mode": "v2_shadow_until_evaluated",
            "live_send_enabled": False,
            "actions_enabled": False,
            "workflow_side_effects_enabled": False,
            "agent_id": AGENT_ID,
            **(metadata or {}),
        },
    )


def _decision(
    *,
    understanding: str,
    next_best_action: str,
    response_plan: str,
    changes: list[AdvisorBrainStateChange] | None = None,
    required_tools: list[str] | None = None,
    missing_facts: list[str] | None = None,
    latest_customer_act: str | None = None,
    needs_human: bool = False,
    metadata: dict[str, Any] | None = None,
) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding=understanding,
        customer_goal="vehicle_credit_sales",
        conversation_goals=["vehicle_credit_sales"],
        known_facts={},
        missing_facts=missing_facts or [],
        next_best_action=next_best_action,
        required_tools=[
            AdvisorBrainToolRequest(
                name=tool_name,
                payload={},
                reason=f"Dinamo shadow requires {tool_name}.",
                required=True,
            )
            for tool_name in (required_tools or [])
        ],
        proposed_state_changes=changes or [],
        response_plan=response_plan,
        confidence=0.92,
        needs_human=needs_human,
        latest_customer_act=latest_customer_act,
        new_information_detected=True,
        metadata=metadata or {},
    )


def _change(
    key: str,
    value: Any,
    *,
    evidence: list[str] | None = None,
    source: str = "user_message",
    explicit: bool = True,
) -> AdvisorBrainStateChange:
    return AdvisorBrainStateChange(
        target="contact_field",
        key=key,
        value=value,
        reason="Dato propuesto desde turno shadow validado por politicas declarativas.",
        evidence=evidence or [],
        confidence=0.92,
        metadata={"source": source, "explicit": explicit},
    )


def _lifecycle(stage: str, *, evidence: list[str]) -> AdvisorBrainStateChange:
    return AdvisorBrainStateChange(
        target="lifecycle",
        key=stage,
        value={"target_stage": stage},
        reason=f"Pipeline shadow avanza a {stage}.",
        evidence=evidence,
        confidence=0.9,
        metadata={"source": "system", "pipeline": "dinamo_vehicle_credit_shadow"},
    )


def _tool(name: str, data: dict[str, Any] | None = None) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=name,
        status="succeeded",
        data={"tenant_id": TENANT_ID, **(data or {})},
        trace_metadata={"tenant_id": TENANT_ID, "dry_run": True},
    )


def _catalog_tool() -> ToolExecutionResult:
    return _tool(
        "catalog.search",
        {
            "query": "R4",
            "items": [
                {
                    "tenant_id": TENANT_ID,
                    "product_id": "dinamo-r4-250-shadow",
                    "sku": "R4-250",
                    "display_name": "R4 250 CC",
                    "cash_price": 62000,
                }
            ],
            "field_updates": [
                {
                    "key": "product_catalog_id",
                    "value": "dinamo-r4-250-shadow",
                    "reason": "catalog.search matched R4 tenant-scoped item.",
                    "evidence": ["tool_result:catalog.search"],
                }
            ],
        },
    )


def _credit_plan_tool(*, seniority_months: int | None = None) -> ToolExecutionResult:
    data: dict[str, Any] = {
        "plan": {
            "code": "sin_comprobantes",
            "name": "Sin Comprobantes",
            "down_payment_percent": 20,
            "income_source": "por fuera",
        },
        "eligible_for_quote": seniority_months is not None and seniority_months >= 6,
    }
    if seniority_months is not None:
        data["field_updates"] = [
            {
                "key": "eligibility_seniority",
                "value": seniority_months >= 6,
                "reason": "credit_plan.resolve validated seniority threshold.",
                "evidence": ["tool_result:credit_plan.resolve"],
            }
        ]
    return _tool("credit_plan.resolve", data)


def _faq_tool(*topics: str) -> ToolExecutionResult:
    return _tool(
        "faq.lookup",
        {
            "topics": list(topics),
            "answers": [
                {
                    "topic": topic,
                    "source_id": f"dinamo-shadow-faq-{topic}",
                    "policy": "informational_only",
                }
                for topic in topics
            ],
        },
    )


def _requirements_tool() -> ToolExecutionResult:
    checklist = [
        {"key": "ine", "label": "INE vigente", "status": "pending"},
        {
            "key": "comprobante_domicilio",
            "label": "Comprobante de domicilio",
            "status": "pending",
        },
    ]
    return _tool(
        "requirements.lookup",
        {
            "plan_code": "sin_comprobantes",
            "checklist": checklist,
            "field_updates": [
                {
                    "key": "requirements_checklist",
                    "value": checklist,
                    "reason": "requirements.lookup returned plan checklist.",
                    "evidence": ["tool_result:requirements.lookup"],
                }
            ],
        },
    )


def _document_tool(
    *,
    attachment_id: str,
    complete: bool,
    missing: list[str],
    received: list[str],
) -> ToolExecutionResult:
    checklist = [
        {
            "key": "ine",
            "status": "validated" if "ine" in received else "pending",
        },
        {
            "key": "comprobante_domicilio",
            "status": "validated" if "comprobante_domicilio" in received else "pending",
        },
    ]
    return _tool(
        "document.check",
        {
            "attachment_id": attachment_id,
            "complete": complete,
            "checklist": checklist,
            "received": received,
            "missing": missing,
            "field_updates": [
                {
                    "key": "requirements_missing",
                    "value": missing,
                    "reason": "document.check computed missing requirements.",
                    "evidence": ["tool_result:document.check", f"attachment:{attachment_id}"],
                },
                {
                    "key": "requirements_complete",
                    "value": complete,
                    "reason": "document.check computed checklist completeness.",
                    "evidence": ["tool_result:document.check", f"attachment:{attachment_id}"],
                },
            ],
        },
    )


def _handoff_tool(reason: str) -> ToolExecutionResult:
    return _tool(
        "handoff.create",
        {
            "dry_run": True,
            "handoff_id": "handoff-shadow-1",
            "reason": reason,
            "field_updates": [
                {
                    "key": "human_handoff_needed",
                    "value": True,
                    "reason": "handoff.create dry-run requested human review.",
                    "evidence": ["tool_result:handoff.create"],
                },
                {
                    "key": "handoff_reason",
                    "value": reason,
                    "reason": "handoff.create dry-run recorded reason.",
                    "evidence": ["tool_result:handoff.create"],
                },
            ],
        },
    )


def _quote_tool() -> ToolExecutionResult:
    product = CanonicalProductReference(
        product_id="dinamo-r4-250-shadow",
        sku="R4-250",
        display_name="R4 250 CC",
        catalog_id="dinamo-shadow-catalog",
        catalog_version_id="shadow-v1",
        evidence=["tool_result:catalog.search"],
    )
    snapshot = QuoteSnapshot(
        snapshot_id="quote-r4-sin-comprobantes-shadow",
        tenant_id=TENANT_ID,
        product=product,
        plan_code="sin_comprobantes",
        plan_name="Sin Comprobantes",
        pricing={
            "cash_price": 62000,
            "payment_amount": 1450,
            "down_payment_percent": 20,
        },
        quote_payload={
            "product_id": product.product_id,
            "plan_code": "sin_comprobantes",
            "dry_run": True,
        },
        evidence=["tool_result:quote.resolve"],
        source_tool="quote.resolve",
    ).with_integrity_hash()
    return _tool("quote.resolve", {"quote_snapshot": snapshot.model_dump(mode="json")})


def _run_turn(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    final_message: str,
    needs_human: bool = False,
    trace_extra: dict[str, Any] | None = None,
) -> ShadowTurn:
    state_write_result = DeterministicStateWriter().build_updates(
        context=context,
        decision=decision,
        tool_results=tool_results,
    )
    output = TurnOutput(
        final_message=final_message,
        field_updates=state_write_result.field_updates,
        lifecycle_update=state_write_result.lifecycle_update,
        confidence=0.92,
        needs_human=needs_human,
        trace_metadata=build_trace_metadata(
            context=context,
            provider="dinamo_shadow_e2e",
            extra={
                "runtime_mode": "v2_shadow_until_evaluated",
                "live_send_enabled": False,
                "actions_enabled": False,
                "workflow_side_effects_enabled": False,
                **(trace_extra or {}),
            },
        ),
    )
    guarded = MandatoryToolGuard().apply(
        context=context,
        decision=decision,
        tool_results=tool_results,
        output=output,
    ).output
    traced = attach_universal_turn_trace(
        context=context,
        decision=decision,
        tool_results=tool_results,
        state_write_result=state_write_result,
        policy_warnings=[],
        output=guarded,
    )
    return ShadowTurn(
        context=context,
        decision=decision,
        tool_results=tool_results,
        state_write_result=state_write_result,
        output=traced,
        trace=traced.trace_metadata["universal_turn_trace"],
    )


def _apply_memory(memory: dict[str, Any], turn: ShadowTurn) -> dict[str, Any]:
    updated = dict(memory)
    for field_update in turn.state_write_result.field_updates:
        updated[field_update.field_key] = field_update.value
    return updated


def _values(turn: ShadowTurn) -> dict[str, Any]:
    return {
        field_update.field_key: field_update.value
        for field_update in turn.state_write_result.field_updates
    }


def _event_types(turn: ShadowTurn) -> list[str]:
    return [str(event.get("event_type")) for event in turn.trace["business_events"]]


def _events(turn: ShadowTurn, event_type: str) -> list[dict[str, Any]]:
    return [
        event
        for event in turn.trace["business_events"]
        if event.get("event_type") == event_type
    ]


def _tool_names(turn: ShadowTurn) -> set[str]:
    return {result.tool_name for result in turn.tool_results}


def _assert_trace_complete(turn: ShadowTurn) -> None:
    for key in (
        "gpt_proposed",
        "atendia_validation",
        "mandatory_tool_decisions",
        "tool_results",
        "state_changes",
        "business_events",
        "guards",
        "lifecycle",
        "final_output",
    ):
        assert key in turn.trace
    assert turn.trace["trace_version"] == "1.0"
    assert turn.trace["tenant_id"] == TENANT_ID
    assert turn.trace["agent_id"] == AGENT_ID
    assert turn.trace["audit"]["raw_trace_preserved"] is True


def _assert_business_events_dry_run(turn: ShadowTurn) -> None:
    assert all(event["status"] == "dry_run" for event in turn.trace["business_events"])
    assert all(
        result["status"] == "dry-run" and result["side_effects_allowed"] is False
        for result in turn.trace["workflow_results"]
    )


def test_dinamo_shadow_contract_loads_real_tenant_proposal() -> None:
    raw = _fixture()
    result = load_tenant_domain_contract(raw, tenant_id=TENANT_ID, agent_id=AGENT_ID)
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)

    assert result.safe_mode is False
    assert raw["runtime_mode"] == "v2_shadow_until_evaluated"
    assert raw["live_send_enabled"] is False
    assert raw["actions_enabled"] is False
    assert raw["workflow_side_effects_enabled"] is False
    assert config.domain == "vehicle_credit_sales"
    assert set(config.field_metadata) >= {
        "product_selection",
        "product_catalog_id",
        "purchase_type",
        "employment_seniority",
        "eligibility_seniority",
        "plan_selection",
        "down_payment_percent",
        "quote_snapshot_id",
        "payment_amount",
        "cash_price",
        "requirements_checklist",
        "requirements_missing",
        "requirements_complete",
        "bureau_mentioned",
        "bureau_status",
        "human_handoff_needed",
        "handoff_reason",
        "followup_status",
    }
    assert set(config.tool_metadata) == {
        "catalog.search",
        "credit_plan.resolve",
        "quote.resolve",
        "requirements.lookup",
        "faq.lookup",
        "document.check",
        "handoff.create",
        "followup.schedule",
    }
    assert set(config.workflow_event_metadata) >= {
        "lead_started",
        "selection_identified",
        "plan_identified",
        "offer_quoted",
        "requirements_requested",
        "document_received",
        "requirements_partial",
        "requirements_complete",
        "human_handoff_requested",
    }
    assert set(config.guard_metadata) >= {
        "mandatory_tool_guard",
        "quote_snapshot_guard",
        "no_approval_guard",
        "workflow_idempotency_guard",
    }


def test_dinamo_shadow_mandatory_tools_block_unvalidated_sensitive_facts() -> None:
    context = _context(
        turn_number=1,
        inbound_text="Precio y requisitos de la R4.",
    )
    decision = _decision(
        understanding="Cliente pide precio y requisitos.",
        next_best_action="answer_sensitive_facts",
        response_plan="Responder precio, requisitos y politica.",
    )

    price = MandatoryToolGuard().apply(
        context=context,
        decision=decision,
        tool_results=[],
        output=TurnOutput(final_message="La R4 queda en $62,000.", confidence=0.9),
    ).output
    requirements = MandatoryToolGuard().apply(
        context=context,
        decision=decision,
        tool_results=[],
        output=TurnOutput(final_message="Manda INE y comprobante de domicilio.", confidence=0.9),
    ).output
    policy = MandatoryToolGuard().apply(
        context=context,
        decision=decision,
        tool_results=[],
        output=TurnOutput(final_message="Aunque tengas buro te podemos aprobar.", confidence=0.9),
    ).output

    assert "$62,000" not in price.final_message
    assert "INE" not in requirements.final_message
    assert "aprobar" not in policy.final_message.casefold()
    assert any(
        item["tool_id"] == "quote.resolve" and item["status"] == "missing"
        for item in price.trace_metadata["mandatory_tool_decisions"]
    )
    assert any(
        item["tool_id"] == "requirements.lookup" and item["status"] == "missing"
        for item in requirements.trace_metadata["mandatory_tool_decisions"]
    )
    assert any(
        item["tool_id"] == "faq.lookup" and item["status"] == "missing"
        for item in policy.trace_metadata["mandatory_tool_decisions"]
    )


def test_dinamo_shadow_state_writer_requires_catalog_and_credit_plan_tools() -> None:
    context = _context(turn_number=1, inbound_text="Me interesa la R4 con plan 20.")
    writer = DeterministicStateWriter()

    without_catalog = writer.build_updates(
        context=context,
        decision=_decision(
            understanding="Cliente menciono modelo.",
            next_best_action="save_model",
            response_plan="Guardar modelo.",
            changes=[_change("product_selection", "R4 250 CC", evidence=["R4"])],
        ),
        tool_results=[],
    )
    without_plan = writer.build_updates(
        context=context,
        decision=_decision(
            understanding="Cliente menciono plan.",
            next_best_action="save_plan",
            response_plan="Guardar plan.",
            changes=[
                _change("plan_selection", "Sin Comprobantes", evidence=["plan 20"]),
                _change("down_payment_percent", 20, evidence=["plan 20"]),
            ],
        ),
        tool_results=[],
    )

    assert without_catalog.field_updates == []
    assert without_catalog.blocked[0]["reason"] == "catalog_match_required"
    assert without_plan.field_updates == []
    assert {item["reason"] for item in without_plan.blocked} == {
        "valid_plan_evidence_required"
    }


def test_dinamo_shadow_six_turn_e2e_produces_dry_run_universal_trace() -> None:
    memory: dict[str, Any] = {}

    turn1 = _run_turn(
        context=_context(
            turn_number=1,
            inbound_text=(
                "Hola, me interesa la R4, traigo buro y me pagan por fuera. "
                "Donde estan?"
            ),
            memory=memory,
        ),
        decision=_decision(
            understanding="Cliente pide modelo, credito, buro, ingreso por fuera y ubicacion.",
            next_best_action="ask_seniority_before_quote",
            response_plan="Validar modelo, plan y FAQ; preguntar antiguedad antes de cotizar.",
            latest_customer_act="model_credit_bureau_income_location",
            missing_facts=["employment_seniority"],
            required_tools=["catalog.search", "credit_plan.resolve", "faq.lookup"],
            changes=[
                _change("product_selection", "R4 250 CC", evidence=["R4"]),
                _change("product_catalog_id", "dinamo-r4-250-shadow", evidence=[]),
                _change("purchase_type", "credito", evidence=["me interesa", "por fuera"]),
                _change("plan_selection", "Sin Comprobantes", evidence=["me pagan por fuera"]),
                _change("down_payment_percent", 20, evidence=["por fuera"]),
                _change("bureau_mentioned", True, evidence=["traigo buro"]),
                _lifecycle("plan_identificado", evidence=["catalog.search", "credit_plan.resolve"]),
            ],
        ),
        tool_results=[
            _catalog_tool(),
            _credit_plan_tool(),
            _faq_tool("buro", "ubicacion"),
        ],
        final_message=(
            "Tengo ubicada la R4 y el plan Sin Comprobantes en shadow. "
            "El buro se revisa con politica, no se convierte en rechazo automatico. "
            "Antes de cotizar necesito saber cuantos meses tienes de antiguedad."
        ),
    )
    memory = _apply_memory(memory, turn1)

    assert {"catalog.search", "credit_plan.resolve", "faq.lookup"} <= _tool_names(turn1)
    assert "quote.resolve" not in _tool_names(turn1)
    assert _values(turn1)["product_selection"] == "R4 250 CC"
    assert _values(turn1)["plan_selection"] == "Sin Comprobantes"
    assert _values(turn1)["bureau_mentioned"] is True
    assert "bureau_status" not in _values(turn1)
    assert turn1.state_write_result.lifecycle_update is not None
    assert turn1.state_write_result.lifecycle_update.target_stage == "plan_identificado"
    assert "selection_identified" in _event_types(turn1)
    assert "plan_identified" in _event_types(turn1)
    assert "offer_quoted" not in _event_types(turn1)

    turn2 = _run_turn(
        context=_context(
            turn_number=2,
            inbound_text="Tengo 8 meses",
            memory=memory,
            lifecycle_stage="plan_identificado",
        ),
        decision=_decision(
            understanding="Cliente dio antiguedad para elegibilidad.",
            next_best_action="quote_with_snapshot",
            response_plan="Cotizar solo con quote.resolve.",
            latest_customer_act="employment_seniority_answer",
            required_tools=["credit_plan.resolve", "quote.resolve"],
            changes=[
                _change("employment_seniority", 8, evidence=["Tengo 8 meses"]),
                _lifecycle("cotizado", evidence=["quote.resolve"]),
            ],
        ),
        tool_results=[_credit_plan_tool(seniority_months=8), _quote_tool()],
        final_message=(
            "Con 8 meses ya puedo usar la cotizacion validada: pago shadow $1,450 "
            "con enganche 20%. La vigencia depende del snapshot."
        ),
    )
    memory = _apply_memory(memory, turn2)

    assert _values(turn2)["employment_seniority"] == 8
    assert _values(turn2)["eligibility_seniority"] is True
    assert _values(turn2)["quote_snapshot_id"] == "quote-r4-sin-comprobantes-shadow"
    assert _values(turn2)["payment_amount"] == 1450
    assert _values(turn2)["cash_price"] == 62000
    assert "offer_quoted" in _event_types(turn2)
    assert _events(turn2, "offer_quoted")[0]["payload"]["quote_snapshot_id"] == (
        "quote-r4-sin-comprobantes-shadow"
    )
    assert turn2.state_write_result.lifecycle_update is not None
    assert turn2.state_write_result.lifecycle_update.target_stage == "cotizado"

    turn3 = _run_turn(
        context=_context(
            turn_number=3,
            inbound_text="Si, pasame que ocupo. No tengo comprobantes.",
            memory=memory,
            lifecycle_stage="cotizado",
        ),
        decision=_decision(
            understanding="Cliente pide requisitos para plan Sin Comprobantes.",
            next_best_action="request_requirements",
            response_plan="Pedir documentos solo desde requirements.lookup.",
            latest_customer_act="requirements_requested",
            required_tools=["requirements.lookup"],
            changes=[_lifecycle("papeleria_solicitada", evidence=["requirements.lookup"])],
        ),
        tool_results=[_requirements_tool()],
        final_message=(
            "Para el plan Sin Comprobantes, en shadow la lista validada pide INE vigente "
            "y comprobante de domicilio."
        ),
    )
    memory = _apply_memory(memory, turn3)

    assert _values(turn3)["requirements_checklist"][0]["key"] == "ine"
    assert "requirements_requested" in _event_types(turn3)
    assert "requirements_complete" not in _event_types(turn3)
    assert turn3.state_write_result.lifecycle_update is not None
    assert turn3.state_write_result.lifecycle_update.target_stage == "papeleria_solicitada"

    turn4 = _run_turn(
        context=_context(
            turn_number=4,
            inbound_text="Te mando la INE al rato",
            memory=memory,
            lifecycle_stage="papeleria_solicitada",
        ),
        decision=_decision(
            understanding="Cliente promete enviar archivo despues, sin adjunto real.",
            next_best_action="wait_for_attachment",
            response_plan="No marcar documentos recibidos sin adjunto.",
            latest_customer_act="future_attachment_promise",
        ),
        tool_results=[],
        final_message="Claro, cuando lo tengas lo revisamos en shadow.",
    )
    memory = _apply_memory(memory, turn4)

    assert "document.check" not in _tool_names(turn4)
    assert "document_received" not in _event_types(turn4)
    assert turn4.state_write_result.field_updates == []
    assert turn4.state_write_result.lifecycle_update is None

    turn5 = _run_turn(
        context=_context(
            turn_number=5,
            inbound_text="[Adjunto INE]",
            memory=memory,
            lifecycle_stage="papeleria_solicitada",
            metadata={
                "attachment_id": "att-ine-shadow",
                "attachments": [{"id": "att-ine-shadow", "type": "image"}],
            },
        ),
        decision=_decision(
            understanding="Cliente envio INE como adjunto real.",
            next_best_action="check_document_partial",
            response_plan="Validar adjunto con document.check.",
            latest_customer_act="document_attachment",
            required_tools=["requirements.lookup", "document.check"],
            changes=[_lifecycle("papeleria_recibida", evidence=["document.check"])],
        ),
        tool_results=[
            _requirements_tool(),
            _document_tool(
                attachment_id="att-ine-shadow",
                complete=False,
                missing=["comprobante_domicilio"],
                received=["ine"],
            ),
        ],
        final_message=(
            "Recibi un archivo y document.check lo marco parcial; falta completar "
            "comprobante de domicilio."
        ),
    )
    memory = _apply_memory(memory, turn5)

    assert "document.check" in _tool_names(turn5)
    assert _values(turn5)["requirements_complete"] is False
    assert _values(turn5)["requirements_missing"] == ["comprobante_domicilio"]
    assert "document_received" in _event_types(turn5)
    assert "requirements_partial" in _event_types(turn5)
    assert "requirements_complete" not in _event_types(turn5)
    assert turn5.state_write_result.lifecycle_update is not None
    assert turn5.state_write_result.lifecycle_update.target_stage == "papeleria_recibida"

    turn6 = _run_turn(
        context=_context(
            turn_number=6,
            inbound_text="[Adjunto comprobante domicilio]",
            memory=memory,
            lifecycle_stage="papeleria_recibida",
            metadata={
                "attachment_id": "att-comprobante-shadow",
                "attachments": [{"id": "att-comprobante-shadow", "type": "image"}],
            },
        ),
        decision=_decision(
            understanding="Cliente envio comprobante y se completo checklist.",
            next_best_action="handoff_for_human_review",
            response_plan="Solicitar revision humana dry-run sin prometer resultado.",
            latest_customer_act="document_attachment_complete",
            needs_human=True,
            required_tools=["requirements.lookup", "document.check", "handoff.create"],
            changes=[_lifecycle("en_revision_humana", evidence=["document.check"])],
            metadata={"handoff_reason": "requirements_complete_needs_human_review"},
        ),
        tool_results=[
            _requirements_tool(),
            _document_tool(
                attachment_id="att-comprobante-shadow",
                complete=True,
                missing=[],
                received=["ine", "comprobante_domicilio"],
            ),
            _handoff_tool("requirements_complete_needs_human_review"),
        ],
        final_message=(
            "Ya quedo la papeleria completa para revision humana. "
            "Esto solo avanza a revision; aun no hay resolucion final."
        ),
        needs_human=True,
        trace_extra={
            "handoff_reason": "requirements_complete_needs_human_review",
            "handoff_requested": True,
        },
    )

    assert _values(turn6)["requirements_complete"] is True
    assert _values(turn6)["human_handoff_needed"] is True
    assert _values(turn6)["handoff_reason"] == "requirements_complete_needs_human_review"
    assert "requirements_complete" in _event_types(turn6)
    assert "human_handoff_requested" in _event_types(turn6)
    assert turn6.state_write_result.lifecycle_update is not None
    assert turn6.state_write_result.lifecycle_update.target_stage == "en_revision_humana"
    assert "aprob" not in turn6.output.final_message.casefold()

    turns = [turn1, turn2, turn3, turn4, turn5, turn6]
    for turn in turns:
        _assert_trace_complete(turn)
        _assert_business_events_dry_run(turn)
        assert turn.output.trace_metadata["workflow_results"]
        assert turn.output.trace_metadata["universal_turn_trace"] == turn.trace
        assert turn.output.trace_metadata["live_send_enabled"] is False
        assert turn.output.trace_metadata["actions_enabled"] is False
        assert turn.output.trace_metadata["workflow_side_effects_enabled"] is False

    stages = [
        turn.state_write_result.lifecycle_update.target_stage
        if turn.state_write_result.lifecycle_update
        else None
        for turn in turns
    ]
    assert stages == [
        "plan_identificado",
        "cotizado",
        "papeleria_solicitada",
        None,
        "papeleria_recibida",
        "en_revision_humana",
    ]
    assert all("aprob" not in turn.output.final_message.casefold() for turn in turns)

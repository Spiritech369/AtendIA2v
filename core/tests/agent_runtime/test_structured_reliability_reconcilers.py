from __future__ import annotations

from atendia.agent_runtime.field_update_reconciler import reconcile_field_updates
from atendia.agent_runtime.handoff_resolver import resolve_handoff
from atendia.agent_runtime.schemas import (
    ActionRequest,
    ActiveAgentContext,
    ContactFieldDefinitionContext,
    LifecycleUpdate,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.structured_reconciler import (
    parse_turn_output_lenient,
    reconcile_structured_output,
)


def _context(
    inbound_text: str = "Me pagan por fuera",
    *,
    reliability: dict | None = None,
) -> TurnContext:
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text=inbound_text,
        active_agent=ActiveAgentContext(
            id="agent-1",
            enabled_action_ids=["assign_conversation"],
            visible_contact_field_keys=["income_type", "CREDITO", "ENGANCHE"],
            allowed_lifecycle_stage_ids=["credito", "doc_incompleta"],
        ),
        contact_fields=[
            ContactFieldDefinitionContext(
                key="income_type",
                label="Ingreso",
                field_type="select",
            ),
            ContactFieldDefinitionContext(
                key="CREDITO",
                label="Credito",
                field_type="select",
            ),
            ContactFieldDefinitionContext(
                key="ENGANCHE",
                label="Enganche",
                field_type="number",
            ),
        ],
        metadata={"structured_reliability": reliability or {}},
    )


def test_lenient_parser_repairs_missing_optional_structured_keys():
    output = parse_turn_output_lenient(
        {
            "final_message": "Claro.",
            "actions": [{"name": "add_tag"}],
            "field_updates": [{"field_key": "income_type", "value": "Nomina"}],
            "confidence": "0.8",
            "needs_human": False,
            "risk_flags": [],
            "trace_metadata": {},
        }
    )

    assert output.final_message == "Claro."
    assert output.actions[0].payload == {}
    assert output.field_updates[0].evidence == []
    assert output.lifecycle_update is None


def test_structured_reconciler_drops_invalid_action_field_and_lifecycle():
    output = TurnOutput(
        final_message="Listo.",
        confidence=0.8,
        actions=[ActionRequest(name="invented_action")],
        field_updates=[
            {
                "field_key": "hidden_field",
                "value": "x",
                "reason": "bad",
                "evidence": ["x"],
                "confidence": 0.9,
                "source": "customer_message",
            }
        ],
        lifecycle_update=LifecycleUpdate(
            target_stage="handoff",
            reason="bad stage",
            evidence=["x"],
            confidence=0.9,
        ),
    )

    reconciled = reconcile_structured_output(_context(), output)

    assert reconciled.actions == []
    assert reconciled.field_updates == []
    assert reconciled.lifecycle_update is None
    assert reconciled.needs_human is True
    assert "human_requested" in reconciled.risk_flags


def test_structured_reconciler_repairs_missing_evidence_and_confidence():
    output = TurnOutput(
        final_message="Te paso con una persona.",
        confidence=0.83,
        actions=[ActionRequest(name="assign_conversation")],
        field_updates=[
            {
                "field_key": "CREDITO",
                "value": "Pensionados",
                "source": "customer_message",
            }
        ],
        lifecycle_update=LifecycleUpdate(target_stage="credito"),
    )

    reconciled = reconcile_structured_output(
        _context("soy pensionado", reliability={}),
        output,
    )

    assert reconciled.actions[0].evidence == ["soy pensionado"]
    assert reconciled.field_updates[0].reason
    assert reconciled.field_updates[0].evidence == ["soy pensionado"]
    assert reconciled.field_updates[0].confidence == 0.83
    assert reconciled.lifecycle_update is not None
    assert reconciled.lifecycle_update.reason
    assert reconciled.lifecycle_update.evidence == ["soy pensionado"]
    assert reconciled.lifecycle_update.confidence == 0.83


def test_field_reconciler_adds_tenant_configured_fields_and_stage():
    reliability = {
        "field_update_rules": [
            {
                "id": "income_sin_comprobantes",
                "field_key": "income_type",
                "kind": "term_value",
                "any_terms": ["por fuera"],
                "value": "Sin Comprobantes",
            },
            {
                "id": "credito_sin_comprobantes",
                "field_key": "CREDITO",
                "kind": "term_value",
                "any_terms": ["por fuera"],
                "value": "Sin Comprobantes",
            },
        ],
        "lifecycle_rules": [
            {
                "id": "credit_flow",
                "target_stage": "credito",
                "any_terms": ["por fuera"],
            }
        ],
    }
    output = TurnOutput(final_message="Va.", confidence=0.9)

    reconciled = reconcile_field_updates(_context(reliability=reliability), output)

    assert {update.field_key for update in reconciled.field_updates} == {
        "income_type",
        "CREDITO",
    }
    assert reconciled.lifecycle_update is not None
    assert reconciled.lifecycle_update.target_stage == "credito"


def test_field_reconciler_supports_dinamo_official_fields_from_tenant_config():
    reliability = {
        "field_update_rules": [
            {
                "id": "seniority_ok",
                "field_key": "CUMPLE_ANTIGUEDAD",
                "kind": "term_value",
                "any_terms": ["tengo 8 meses"],
                "value": True,
            },
            {
                "id": "plan_nomina_tarjeta",
                "field_key": "PLAN",
                "kind": "term_value",
                "any_terms": ["nomina en tarjeta"],
                "value": "Nómina Tarjeta",
            },
            {
                "id": "moto_interes",
                "field_key": "MOTO_INTERES",
                "kind": "term_value",
                "any_terms": ["dinamo r4"],
                "value": "Dinamo R4",
            },
        ],
        "lifecycle_rules": [
            {
                "id": "official_plan_stage",
                "target_stage": "plan",
                "any_terms": ["nomina en tarjeta"],
            }
        ],
    }
    context = TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Tengo 8 meses y me pagan nomina en tarjeta. Me interesa la Dinamo R4.",
        active_agent=ActiveAgentContext(
            id="agent-1",
            enabled_action_ids=[],
            visible_contact_field_keys=[
                "CUMPLE_ANTIGUEDAD",
                "PLAN",
                "MOTO_INTERES",
                "DOCUMENTOS",
                "DOCUMENTOS_COMPLETOS",
            ],
            allowed_lifecycle_stage_ids=[
                "nuevos",
                "plan",
                "cliente_potencial",
                "papeleria_incompleta",
                "papeleria_completa",
            ],
        ),
        contact_fields=[
            ContactFieldDefinitionContext(
                key="CUMPLE_ANTIGUEDAD",
                label="Cumple antiguedad",
                field_type="boolean",
            ),
            ContactFieldDefinitionContext(key="PLAN", label="Plan", field_type="select"),
            ContactFieldDefinitionContext(
                key="MOTO_INTERES",
                label="Moto de interes",
                field_type="text",
            ),
        ],
        metadata={"structured_reliability": reliability},
    )

    reconciled = reconcile_field_updates(context, TurnOutput(final_message="Va.", confidence=0.9))

    assert {update.field_key: update.value for update in reconciled.field_updates} == {
        "CUMPLE_ANTIGUEDAD": True,
        "PLAN": "Nómina Tarjeta",
        "MOTO_INTERES": "Dinamo R4",
    }
    assert reconciled.lifecycle_update is not None
    assert reconciled.lifecycle_update.target_stage == "plan"


def test_handoff_resolver_sets_needs_human_and_valid_preview_action():
    output = TurnOutput(
        final_message="Te paso con una persona.",
        confidence=0.9,
        lifecycle_update=LifecycleUpdate(
            target_stage="handoff",
            reason="human",
            evidence=["Quiero hablar con alguien"],
            confidence=0.9,
        ),
    )

    resolved = resolve_handoff(_context("Quiero hablar con alguien"), output)

    assert resolved.needs_human is True
    assert resolved.lifecycle_update is None
    assert resolved.actions[0].name == "assign_conversation"
    assert "human_requested" in resolved.risk_flags

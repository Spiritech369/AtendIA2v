from __future__ import annotations

from atendia.agent_runtime.operational_state_reconciler import (
    OperationalStateInput,
    OperationalStateReconciler,
)
from atendia.agent_runtime.schemas import ActiveAgentContext, FieldUpdate, TurnContext, TurnOutput
from tests.agent_runtime.test_operational_state_reconciler import (
    DINAMO_OPERATIONAL_STATE_CONFIG,
)

FIELDS = [
    "Cumple_Antiguedad",
    "Plan_Credito",
    "Plan_Enganche",
    "Moto",
    "Cotizacion_Enviada",
    "Ultima_Cotizacion",
    "Doc_Completos",
    "Docs_Checklist",
    "Handoff_Humano",
]
STAGES = [
    "nuevos",
    "plan",
    "cliente_potencial",
    "papeleria_incompleta",
    "papeleria_completa",
    "galgo",
]


def _context(text: str) -> TurnContext:
    return TurnContext(
        tenant_id="tenant",
        conversation_id="conversation",
        inbound_text=text,
        metadata={"tenant_config": {"ruleset": {"operational_state": DINAMO_OPERATIONAL_STATE_CONFIG}}},
        active_agent=ActiveAgentContext(
            visible_contact_field_keys=FIELDS,
            allowed_lifecycle_stage_ids=STAGES,
        ),
    )


def _values(output: TurnOutput) -> dict:
    return {update.field_key: update.value for update in output.field_updates}


def test_nomina_tarjeta_not_overwritten_by_receipts_followup() -> None:
    first = OperationalStateReconciler().reconcile(
        _context("Me depositan en tarjeta"),
        TurnOutput(),
    )
    first_values = _values(first)
    assert first_values["Plan_Credito"] == "Nomina Tarjeta"
    assert first_values["Plan_Enganche"] == "10%"

    second = OperationalStateReconciler().reconcile(
        _context("Si tengo recibos de nomina"),
        TurnOutput(),
        OperationalStateInput(current_fields=first_values),
    )
    second_values = _values(second)
    assert second_values["Plan_Enganche"] == "10%"
    assert second_values.get("Plan_Credito") != "Nomina Recibos"


def test_nomina_recibos_cash_with_receipts() -> None:
    output = OperationalStateReconciler().reconcile(
        _context("Me pagan efectivo pero tengo recibos"),
        TurnOutput(),
    )
    values = _values(output)
    assert values["Plan_Credito"] == "Nomina Recibos"
    assert values["Plan_Enganche"] == "15%"


def test_stage_plan_only_requires_plan_and_down_payment() -> None:
    output = OperationalStateReconciler().reconcile(
        _context("Me pagan por fuera"),
        TurnOutput(),
    )
    assert output.lifecycle_update
    assert output.lifecycle_update.target_stage == "plan"


def test_stage_plan_with_moto_but_no_quote_stays_plan() -> None:
    output = OperationalStateReconciler().reconcile(
        _context("Me pagan por fuera y quiero la R4"),
        TurnOutput(),
    )
    assert output.lifecycle_update
    assert output.lifecycle_update.target_stage == "plan"


def test_stage_plan_moto_quote_becomes_cliente_potencial() -> None:
    output = OperationalStateReconciler().reconcile(
        _context("Cotizame la R4"),
        TurnOutput(field_updates=[FieldUpdate(field_key="Moto", value="R4")]),
        OperationalStateInput(
            current_fields={"Plan_Credito": "Sin Comprobantes", "Plan_Enganche": "20%"},
            quote_snapshot={"status": "ok", "moto": "R4"},
        ),
    )
    assert output.lifecycle_update
    assert output.lifecycle_update.target_stage == "cliente_potencial"


def test_contado_moto_quote_becomes_cliente_potencial() -> None:
    output = OperationalStateReconciler().reconcile(
        _context("Quiero comprar de contado la R4"),
        TurnOutput(field_updates=[FieldUpdate(field_key="Moto", value="R4")]),
        OperationalStateInput(
            current_fields={"Plan_Credito": "Contado", "Plan_Enganche": "100%"},
            quote_snapshot={"status": "ok", "moto": "R4", "plan_credito": "Contado"},
        ),
    )
    assert output.lifecycle_update
    assert output.lifecycle_update.target_stage == "cliente_potencial"

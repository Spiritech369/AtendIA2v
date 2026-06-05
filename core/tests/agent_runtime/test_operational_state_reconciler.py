from __future__ import annotations

from atendia.agent_runtime.operational_state_reconciler import (
    OperationalStateInput,
    OperationalStateReconciler,
)
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    FieldUpdate,
    TurnContext,
    TurnOutput,
)

FIELDS = [
    "Cumple_Antiguedad",
    "Plan_Credito",
    "Plan_Enganche",
    "Moto",
    "Doc_Completos",
    "Docs_Checklist",
    "Handoff_Humano",
    "Autorizado",
    "Cotizacion_Enviada",
    "Ultima_Cotizacion",
]
STAGES = [
    "nuevos",
    "plan",
    "cliente_potencial",
    "papeleria_incompleta",
    "papeleria_completa",
    "galgo",
    "sistema",
    "cliente_cerrado",
]

DINAMO_OPERATIONAL_STATE_CONFIG = {
    "fields": {
        "seniority": "Cumple_Antiguedad",
        "plan": "Plan_Credito",
        "down_payment": "Plan_Enganche",
        "product": "Moto",
        "documents_complete": "Doc_Completos",
        "documents_checklist": "Docs_Checklist",
        "handoff": "Handoff_Humano",
        "quote_sent": "Cotizacion_Enviada",
        "last_quote": "Ultima_Cotizacion",
    },
    "field_aliases": {
        "plan": "Plan_Credito",
        "moto_interes": "Moto",
        "modelo_interes": "Moto",
        "documentos_completos": "Doc_Completos",
        "documentos": "Docs_Checklist",
    },
    "blocked_auto_fields": ["Autorizado"],
    "seniority": {
        "minimum_months": 6,
        "negative_phrases": ["no trabajo", "apenas entre", "acabo de entrar"],
        "year_units": ["ano", "anos"],
    },
    "plans": [
        {
            "value": "Nomina Tarjeta",
            "down_payment": "10%",
            "aliases": ["deposit", "tarjeta"],
            "weak_aliases": ["recibo"],
        },
        {
            "value": "Nomina Recibos",
            "down_payment": "15%",
            "aliases": ["me pagan con recib", "efectivo pero tengo recibos"],
            "weak_aliases": ["recibo"],
        },
        {"value": "Pensionados", "down_payment": "10%", "aliases": ["pension"]},
        {"value": "Negocio SAT", "down_payment": "15%", "aliases": ["sat", "negocio"]},
        {
            "value": "Sin Comprobantes",
            "down_payment": "20%",
            "aliases": ["por fuera", "sin comprob"],
        },
        {"value": "Guardia", "down_payment": "30%", "aliases": ["guardia", "seguridad"]},
        {"value": "Contado", "down_payment": "100%", "aliases": ["contado"]},
    ],
    "product_aliases": {"r4": "R4", "comando": "Comando", "adventure": "Adventure", "u5": "U5"},
    "quote_snapshot": {
        "product_keys": ["moto"],
        "plan_keys": ["plan_credito"],
        "down_payment_keys": ["plan_enganche"],
        "quote_sent_default": True,
    },
    "documents": {
        "default_complete_when_missing": False,
        "accepted_status": "accepted",
        "progress_statuses": ["received", "accepted", "rejected", "needs_review"],
    },
    "handoff": {
        "positive_phrases": ["humano", "asesor", "persona", "alguien real", "pasame con alguien"],
        "paid_change_all_phrases": ["pague", "cambiar"],
        "risk_phrases": ["ingresos de tercero", "documento sospechoso", "documento falso"],
        "default_false_when_missing": True,
    },
    "stages": {
        "manual": ["sistema", "cliente_cerrado"],
        "seniority_failed": "galgo",
        "plan_ready": "plan",
        "quote_ready": "cliente_potencial",
        "documents_incomplete": "papeleria_incompleta",
        "documents_complete": "papeleria_completa",
        "documents_incomplete_requires_attachment": True,
    },
}


def _context(text: str = "Tengo 8 meses y me depositan en tarjeta") -> TurnContext:
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


def test_cumple_antiguedad_true_se_guarda_boolean() -> None:
    out = OperationalStateReconciler().reconcile(_context(), TurnOutput())

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Cumple_Antiguedad"] is True


def test_cumple_antiguedad_false_y_galgo() -> None:
    out = OperationalStateReconciler().reconcile(_context("Tengo 2 meses trabajando"), TurnOutput())

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Cumple_Antiguedad"] is False
    assert out.lifecycle_update
    assert out.lifecycle_update.target_stage == "galgo"


def test_plan_stage_from_plan_y_enganche() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Me pagan por fuera"),
        TurnOutput(),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Plan_Credito"] == "Sin Comprobantes"
    assert values["Plan_Enganche"] == "20%"
    assert out.lifecycle_update
    assert out.lifecycle_update.target_stage == "plan"


def test_cliente_potencial_from_quote_snapshot() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Cotizame la R4"),
        TurnOutput(field_updates=[FieldUpdate(field_key="Moto", value="R4")]),
        OperationalStateInput(
            current_fields={"Plan_Credito": "Contado", "Plan_Enganche": "100%"},
            quote_snapshot={"status": "ok", "moto": "R4", "plan_credito": "Contado"},
        ),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Cotizacion_Enviada"] is True
    assert out.lifecycle_update
    assert out.lifecycle_update.target_stage == "cliente_potencial"


def test_quote_snapshot_canonicalizes_moto_field() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Quiero la R4 de contado"),
        TurnOutput(field_updates=[FieldUpdate(field_key="Moto", value="R4")]),
        OperationalStateInput(
            current_fields={"Plan_Credito": "Contado", "Plan_Enganche": "100%"},
            quote_snapshot={
                "status": "ok",
                "moto": "R4 250 CC",
                "plan_credito": "Contado",
                "plan_enganche": "100%",
            },
        ),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Moto"] == "R4 250 CC"


def test_papeleria_incompleta_only_with_attachment() -> None:
    checklist = [{"key": "INE", "status": "received"}]
    out = OperationalStateReconciler().reconcile(
        _context("Te mando la INE"),
        TurnOutput(),
        OperationalStateInput(
            current_fields={"Docs_Checklist": checklist, "Doc_Completos": False},
            attachments_present=False,
        ),
    )
    assert out.lifecycle_update is None

    out_with_attachment = OperationalStateReconciler().reconcile(
        _context("Te mando la INE"),
        TurnOutput(),
        OperationalStateInput(
            current_fields={"Docs_Checklist": checklist, "Doc_Completos": False},
            attachments_present=True,
        ),
    )
    assert out_with_attachment.lifecycle_update
    assert out_with_attachment.lifecycle_update.target_stage == "papeleria_incompleta"


def test_ai_papeleria_incompleta_without_attachment_is_refused() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Te mando la INE"),
        TurnOutput(
            lifecycle_update={
                "target_stage": "papeleria_incompleta",
                "reason": "customer mentioned INE",
                "evidence": ["Te mando la INE"],
                "confidence": 1,
            }
        ),
        OperationalStateInput(attachments_present=False),
    )

    assert out.lifecycle_update is None
    assert out.trace_metadata["skipped_stage_reason"] == "document progress requires attachment"


def test_handoff_humano_from_human_request_and_autorizado_blocked() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Quiero hablar con alguien real"),
        TurnOutput(
            field_updates=[FieldUpdate(field_key="Autorizado", value=True)],
        ),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Handoff_Humano"] is True
    assert "Autorizado" not in values


def test_documentos_mama_no_handoff_or_papeleria() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Puedo mandar documentos de mi mama? Seria su comprobante de domicilio."),
        TurnOutput(needs_human=True, risk_flags=["missing_required_citations"]),
        OperationalStateInput(current_fields={"Cumple_Antiguedad": True}),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Handoff_Humano"] is False
    assert out.lifecycle_update is None


def test_doc_completos_true_sets_handoff() -> None:
    checklist = [{"key": "INE", "status": "accepted"}]
    out = OperationalStateReconciler().reconcile(
        _context("Ya envie todos los documentos"),
        TurnOutput(),
        OperationalStateInput(
            current_fields={"Docs_Checklist": checklist},
            attachments_present=True,
        ),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Doc_Completos"] is True
    assert values["Handoff_Humano"] is True


def test_provider_technical_risk_does_not_set_handoff() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Me interesa la Adventure"),
        TurnOutput(needs_human=True, risk_flags=["provider_error"]),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Handoff_Humano"] is False


def test_plan_lock_keeps_nomina_tarjeta_when_receipts_are_weak_followup() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Si tengo recibos de nomina"),
        TurnOutput(),
        OperationalStateInput(current_fields={"Plan_Credito": "Nomina Tarjeta"}),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Plan_Enganche"] == "10%"
    assert "Plan_Credito" not in values
    plan_lock_reason = out.trace_metadata["operational_reconciler_changes"]["plan_lock_reason"]
    assert "kept Nomina Tarjeta" in plan_lock_reason


def test_plan_recibos_strong_when_cash_with_receipts() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Me pagan en efectivo pero tengo recibos"),
        TurnOutput(),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Plan_Credito"] == "Nomina Recibos"
    assert values["Plan_Enganche"] == "15%"


def test_paid_customer_changing_moto_sets_handoff() -> None:
    out = OperationalStateReconciler().reconcile(
        _context("Ya pague y quiero cambiar de moto"),
        TurnOutput(),
    )

    values = {update.field_key: update.value for update in out.field_updates}
    assert values["Handoff_Humano"] is True


def test_sistema_y_cliente_cerrado_never_auto() -> None:
    for stage in ("sistema", "cliente_cerrado"):
        out = OperationalStateReconciler().reconcile(
            _context("mover manual"),
            TurnOutput(
                lifecycle_update={
                    "target_stage": stage,
                    "reason": "bad",
                    "evidence": ["bad"],
                    "confidence": 1,
                }
            ),
        )
        assert out.lifecycle_update is None

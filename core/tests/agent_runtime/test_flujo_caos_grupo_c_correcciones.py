"""Batería Dinamo — Grupo C (correcciones de datos), SIN API.

Ejecuta el guion de corrección del operador por la capa REAL del runtime
(``apply_field_proposals``: la misma validación/auditoría que corre en vivo):

    tengo 9 meses          -> perdón, tengo 2 años
    me pagan por tarjeta   -> no, realmente es transferencia
    quiero la Metro        -> mejor la Comando

Esperado: cada corrección actualiza SOLO ese campo (audit
``corrected_previous_value``), nunca reinicia el resto del estado, y las
reglas de plan re-resuelven con el estado corregido.
"""

from atendia.agent_runtime.respond_style_field_state import apply_field_proposals
from atendia.agent_runtime.respond_style_real_facts_executor import (
    RealFactsToolExecutor,
)
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    LLMToolCallProposal,
)

FIELD_POLICIES = [
    {"field_key": "employment_seniority", "label": "antiguedad"},
    {
        "field_key": "income_type",
        "label": "ingresos",
        "allowed_values": ["nomina", "transferencia", "tarjeta", "efectivo"],
    },
    {"field_key": "selected_model", "label": "modelo"},
    {"field_key": "payroll_receipts_status", "label": "recibos",
     "allowed_values": ["disponibles", "por_pedir", "no_tiene"]},
]


def _propose(key: str, value, evidence="transcript:latest_customer_message"):
    return {"field_key": key, "value": value, "evidence": [evidence]}


def test_correcciones_actualizan_solo_ese_campo() -> None:
    state: dict = {}

    # turno 1: "tengo 9 meses"
    r1 = apply_field_proposals(
        [_propose("employment_seniority", "9 meses")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    assert r1.accepted_count == 1
    state = r1.new_values

    # turno 2: "me pagan por tarjeta"
    r2 = apply_field_proposals(
        [_propose("income_type", "tarjeta")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    state = r2.new_values
    assert state == {"employment_seniority": "9 meses", "income_type": "tarjeta"}

    # turno 3: "perdón, tengo 2 años" — corrige SOLO antigüedad
    r3 = apply_field_proposals(
        [_propose("employment_seniority", "2 años")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    state = r3.new_values
    entry = r3.audit[0]
    assert entry.status == "accepted"
    assert entry.previous_value == "9 meses"
    assert state["employment_seniority"] == "2 años"
    assert state["income_type"] == "tarjeta"  # intacto

    # turno 4: "no, realmente es transferencia" — corrige SOLO ingreso
    r4 = apply_field_proposals(
        [_propose("income_type", "transferencia")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    state = r4.new_values
    assert r4.audit[0].previous_value == "tarjeta"
    assert state["employment_seniority"] == "2 años"  # intacto

    # turno 5-6: "quiero la Metro" -> "mejor la Comando"
    r5 = apply_field_proposals(
        [_propose("selected_model", "metro_city")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    state = r5.new_values
    r6 = apply_field_proposals(
        [_propose("selected_model", "comando_400_cc")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    state = r6.new_values
    assert r6.audit[0].previous_value == "metro_city"
    assert state == {
        "employment_seniority": "2 años",
        "income_type": "transferencia",
        "selected_model": "comando_400_cc",
    }


def test_correccion_invalida_no_destruye_estado() -> None:
    state = {"income_type": "transferencia", "employment_seniority": "2 años"}
    # valor fuera de allowed_values -> rechazado, estado intacto
    result = apply_field_proposals(
        [_propose("income_type", "bitcoin")],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    assert result.rejected_count == 1
    assert result.new_values["income_type"] == "transferencia"
    # propuesta sin evidencia -> rechazada
    result2 = apply_field_proposals(
        [{"field_key": "employment_seniority", "value": "5 años", "evidence": []}],
        field_policies=FIELD_POLICIES,
        current_values=state,
    )
    assert result2.rejected_count == 1
    assert result2.new_values["employment_seniority"] == "2 años"


def test_plan_se_reresuelve_con_estado_corregido() -> None:
    """Tras corregir tarjeta->transferencia el plan sigue resolviendo por las
    reglas del tenant con el estado corregido (por_pedir -> Nómina Tarjeta)."""
    rules = [
        {
            "when": {
                "income_type": ["nomina", "tarjeta", "transferencia"],
                "payroll_receipts_status": ["por_pedir"],
            },
            "plan": "Nómina Tarjeta",
        },
    ]
    binding = {
        "name": "credit_plan.resolve",
        "real_source": "knowledge_plans",
        "preconditions": ["income_type"],
        "selection_rules": rules,
    }
    plans = [
        {"tipo_credito": "Nómina Tarjeta", "plan_credito": "10%", "texto_retrieval": "t"}
    ]
    executor = RealFactsToolExecutor([binding], {"requirement_plans": plans})
    corrected_state = {
        "income_type": "transferencia",  # corregido desde "tarjeta"
        "payroll_receipts_status": "por_pedir",
    }
    result = executor.execute_tool(
        LLMToolCallProposal(
            tool_name="credit_plan.resolve", arguments={}, reason="resolver plan"
        ),
        AgentContextPackage(agent_identity={"contact_state": corrected_state}),
    )
    assert result.status == "succeeded"
    assert result.facts["plans"][0]["tipo_credito"] == "Nómina Tarjeta"

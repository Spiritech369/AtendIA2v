"""Deterministic plan selection: tenant binding selection_rules decide the
plan from contact state; without a matching rule the tool fails closed
(skipped) instead of letting the LLM pick among fuzzy matches."""

from atendia.agent_runtime.respond_style_real_facts_executor import (
    RealFactsToolExecutor,
)
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    LLMToolCallProposal,
)

PLANS = [
    {"tipo_credito": "Nómina Tarjeta", "plan_credito": "10%", "texto_retrieval": "t"},
    {"tipo_credito": "Nómina Recibos", "plan_credito": "15%", "texto_retrieval": "r"},
    {"tipo_credito": "Sin Comprobantes", "plan_credito": "20%", "texto_retrieval": "s"},
]

RULES = [
    {
        "when": {
            "income_type": ["nomina", "tarjeta", "deposito"],
            "payroll_receipts_status": ["disponibles"],
        },
        "plan": "Nómina Recibos",
    },
    {
        "when": {
            "income_type": ["nomina", "tarjeta", "deposito"],
            "payroll_receipts_status": ["por_pedir", "no_tiene"],
        },
        "plan": "Nómina Tarjeta",
    },
    {"when": {"income_type": ["sin_comprobantes", "efectivo"]}, "plan": "Sin Comprobantes"},
]

BINDING = {
    "name": "credit_plan.resolve",
    "real_source": "knowledge_plans",
    "preconditions": ["income_type"],
    "selection_rules": RULES,
}


def _context(contact_state: dict) -> AgentContextPackage:
    return AgentContextPackage(agent_identity={"contact_state": contact_state})


def _executor() -> RealFactsToolExecutor:
    return RealFactsToolExecutor([BINDING], {"requirement_plans": PLANS})


def _call() -> LLMToolCallProposal:
    return LLMToolCallProposal(
        tool_name="credit_plan.resolve",
        arguments={},
        reason="resolver plan del cliente",
    )


def test_deposit_with_receipts_pending_resolves_nomina_tarjeta() -> None:
    result = _executor().execute_tool(
        _call(),
        _context({"income_type": "nomina", "payroll_receipts_status": "por_pedir"}),
    )
    assert result.status == "succeeded"
    plans = result.facts["plans"]
    assert len(plans) == 1
    assert plans[0]["tipo_credito"] == "Nómina Tarjeta"
    assert result.facts["selected_by_rule"] is True


def test_receipts_available_resolves_nomina_recibos() -> None:
    result = _executor().execute_tool(
        _call(),
        _context({"income_type": "tarjeta", "payroll_receipts_status": "disponibles"}),
    )
    assert result.status == "succeeded"
    assert result.facts["plans"][0]["tipo_credito"] == "Nómina Recibos"


def test_no_matching_rule_fails_closed() -> None:
    # income known but receipts status unknown -> no rule matches -> skip
    result = _executor().execute_tool(
        _call(), _context({"income_type": "nomina"})
    )
    assert result.status == "skipped"
    assert result.error_code == "missing_precondition:selection_rule"


def test_list_valued_state_matches_by_element() -> None:
    rules = [
        {
            "when": {
                "payroll_receipts_status": ["no_tiene"],
                "nomina_visible_en_estado": ["si"],
            },
            "plan": "Nómina Tarjeta",
        },
    ]
    binding = {**BINDING, "selection_rules": rules}
    executor = RealFactsToolExecutor([binding], {"requirement_plans": PLANS})
    result = executor.execute_tool(
        _call(),
        _context(
            {
                "income_type": "transferencia",
                "payroll_receipts_status": "no_tiene",
                "nomina_visible_en_estado": "si",
                "documentos_recibidos": ["estado_cuenta", "nomina_en_estado"],
            }
        ),
    )
    assert result.status == "succeeded"
    assert result.facts["plans"][0]["tipo_credito"] == "Nómina Tarjeta"


def test_no_tiene_without_document_evidence_fails_closed() -> None:
    rules = [
        {
            "when": {
                "payroll_receipts_status": ["no_tiene"],
                "nomina_visible_en_estado": ["si", "no"],
            },
            "plan": "Nómina Tarjeta",
        },
    ]
    binding = {**BINDING, "selection_rules": rules}
    executor = RealFactsToolExecutor([binding], {"requirement_plans": PLANS})
    result = executor.execute_tool(
        _call(),
        _context({"income_type": "deposito", "payroll_receipts_status": "no_tiene"}),
    )
    assert result.status == "skipped"
    assert result.error_code == "missing_precondition:selection_rule"


RULES_V3 = [
    {"when": {"es_guardia": ["si"]}, "plan": "Guardia de Seguridad"},
    {"when": {"income_type": ["pensionado", "pension"]}, "plan": "Pensionados"},
    {
        "when": {
            "income_type": ["nomina", "tarjeta", "deposito"],
            "payroll_receipts_status": ["por_pedir"],
            "nomina_oficial_valida": ["no"],
        },
        "plan": "Sin Comprobantes",
    },
    {
        "when": {
            "income_type": ["nomina", "tarjeta", "deposito"],
            "payroll_receipts_status": ["por_pedir"],
        },
        "plan": "Nómina Tarjeta",
    },
]

PLANS_V3 = [
    *PLANS,
    {"tipo_credito": "Guardia de Seguridad", "plan_credito": "30%", "texto_retrieval": "g"},
    {"tipo_credito": "Pensionados", "plan_credito": "10%", "texto_retrieval": "p"},
]


def _executor_v3() -> RealFactsToolExecutor:
    binding = {**BINDING, "selection_rules": RULES_V3}
    return RealFactsToolExecutor([binding], {"requirement_plans": PLANS_V3})


def test_guardia_overrides_everything() -> None:
    result = _executor_v3().execute_tool(
        _call(),
        _context(
            {
                "es_guardia": "si",
                "income_type": "nomina",
                "payroll_receipts_status": "disponibles",
            }
        ),
    )
    assert result.facts["plans"][0]["tipo_credito"] == "Guardia de Seguridad"


def test_pensionado_resolves_pensionados() -> None:
    result = _executor_v3().execute_tool(
        _call(), _context({"income_type": "pensionado"})
    )
    assert result.facts["plans"][0]["tipo_credito"] == "Pensionados"


def test_por_pedir_with_invalid_sample_goes_sin_comprobantes() -> None:
    result = _executor_v3().execute_tool(
        _call(),
        _context(
            {
                "income_type": "deposito",
                "payroll_receipts_status": "por_pedir",
                "nomina_oficial_valida": "no",
            }
        ),
    )
    assert result.facts["plans"][0]["tipo_credito"] == "Sin Comprobantes"


def test_por_pedir_without_sample_stays_tentative_tarjeta() -> None:
    result = _executor_v3().execute_tool(
        _call(),
        _context({"income_type": "deposito", "payroll_receipts_status": "por_pedir"}),
    )
    assert result.facts["plans"][0]["tipo_credito"] == "Nómina Tarjeta"


def test_without_rules_keeps_fuzzy_behavior() -> None:
    binding = {k: v for k, v in BINDING.items() if k != "selection_rules"}
    executor = RealFactsToolExecutor([binding], {"requirement_plans": PLANS})
    result = executor.execute_tool(_call(), _context({"income_type": "nomina"}))
    assert result.status == "succeeded"
    assert len(result.facts["plans"]) >= 2

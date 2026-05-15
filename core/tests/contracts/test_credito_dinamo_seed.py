"""M7 smoke: the starter "Crédito Dinamo" pipeline shape validates
against the contract.

We don't run the seed script here (it requires a live DB). Instead we
import the constant and round-trip it through PipelineDefinition. If
this test fails, the seed script would either crash on insert or insert
data the runner can't load.
"""

from __future__ import annotations

from atendia.contracts.pipeline_definition import (
    AutoEnterRules,
    PipelineDefinition,
)


def _load_seed() -> dict:
    # Import inline so a syntax error in the script (rare but possible)
    # surfaces as a clear failure rather than a collection error.
    from scripts.seed_zored_user import CREDITO_DINAMO_PIPELINE

    return CREDITO_DINAMO_PIPELINE


def test_credito_dinamo_round_trips_through_contract():
    raw = _load_seed()
    pipeline = PipelineDefinition.model_validate(raw)
    assert pipeline.version == 1
    assert pipeline.fallback == "escalate_to_human"
    # Five stages: nuevo -> cliente_potencial -> documentos_pendientes ->
    # papeleria_completa -> cerrado.
    assert [s.id for s in pipeline.stages] == [
        "nuevo",
        "cliente_potencial",
        "documentos_pendientes",
        "papeleria_completa",
        "cerrado",
    ]


def test_credito_dinamo_cliente_potencial_rule_is_field_existence():
    pipeline = PipelineDefinition.model_validate(_load_seed())
    cp = next(s for s in pipeline.stages if s.id == "cliente_potencial")
    assert isinstance(cp.auto_enter_rules, AutoEnterRules)
    assert cp.auto_enter_rules.enabled is True
    assert cp.auto_enter_rules.match == "all"
    fields = sorted(c.field for c in cp.auto_enter_rules.conditions)
    assert fields == ["modelo_interes", "plan_credito", "tipo_enganche"]
    assert all(c.operator == "exists" for c in cp.auto_enter_rules.conditions)


def test_credito_dinamo_papeleria_completa_rule_is_doc_statuses():
    pipeline = PipelineDefinition.model_validate(_load_seed())
    pap = next(s for s in pipeline.stages if s.id == "papeleria_completa")
    assert pap.auto_enter_rules is not None
    fields = sorted(c.field for c in pap.auto_enter_rules.conditions)
    assert fields == [
        "DOCS_COMPROBANTE_DOMICILIO.status",
        "DOCS_ESTADOS_CUENTA.status",
        "DOCS_INE.status",
        "DOCS_RECIBOS_NOMINA.status",
    ]
    # Every condition is equals "ok" — the shape DocumentRuleBuilder
    # produces, so the pre-fill heuristic will recognise this when
    # loaded into the editor.
    for c in pap.auto_enter_rules.conditions:
        assert c.operator == "equals"
        assert c.value == "ok"


def test_credito_dinamo_cerrado_is_terminal():
    pipeline = PipelineDefinition.model_validate(_load_seed())
    cerrado = next(s for s in pipeline.stages if s.id == "cerrado")
    assert cerrado.is_terminal is True
    # Must NOT allow_auto_backward (terminal stage; the contract enforces
    # mutual exclusion of the two flags).
    assert cerrado.allow_auto_backward is False


def test_credito_dinamo_evaluator_picks_cliente_potencial_with_full_fields():
    """End-to-end vibe check: the evaluator's pure functions agree with
    the seed's intent for the prototypical 'qualified lead' input."""
    from atendia.state_machine.pipeline_evaluator import (
        evaluate_rule_group,
        select_best_stage,
    )

    pipeline = PipelineDefinition.model_validate(_load_seed())
    fields = {
        "modelo_interes": "DM200 2026",
        "plan_credito": "36 meses",
        "tipo_enganche": "efectivo",
    }
    matching = [
        s
        for s in pipeline.stages
        if s.auto_enter_rules and evaluate_rule_group(s.auto_enter_rules, fields)
    ]
    pick = select_best_stage(
        matching=matching,
        current_stage_id="nuevo",
        pipeline=pipeline,
    )
    assert pick is not None
    assert pick.id == "cliente_potencial"


def test_credito_dinamo_evaluator_picks_papeleria_when_all_docs_ok():
    from atendia.state_machine.pipeline_evaluator import (
        evaluate_rule_group,
        select_best_stage,
    )

    pipeline = PipelineDefinition.model_validate(_load_seed())
    fields = {
        # Cliente_potencial fields stay set (forward pressure)
        "modelo_interes": "DM200",
        "plan_credito": "36",
        "tipo_enganche": "efectivo",
        # All docs ok
        "DOCS_INE": {"status": "ok"},
        "DOCS_COMPROBANTE_DOMICILIO": {"status": "ok"},
        "DOCS_ESTADOS_CUENTA": {"status": "ok"},
        "DOCS_RECIBOS_NOMINA": {"status": "ok"},
    }
    matching = [
        s
        for s in pipeline.stages
        if s.auto_enter_rules and evaluate_rule_group(s.auto_enter_rules, fields)
    ]
    # Both cliente_potencial AND papeleria_completa match — the evaluator
    # should pick papeleria_completa (later in the stage list).
    pick = select_best_stage(
        matching=matching,
        current_stage_id="documentos_pendientes",
        pipeline=pipeline,
    )
    assert pick is not None
    assert pick.id == "papeleria_completa"

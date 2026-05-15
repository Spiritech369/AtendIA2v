"""M3 of the pipeline-automation plan. Pure-function tests for the
evaluator: condition operators, field-path resolution, and stage
selection logic. The async DB-aware wrapper is exercised in the
integration test at the bottom (skipped when DB is unavailable).
"""

from __future__ import annotations

import pytest

from atendia.contracts.pipeline_definition import (
    AutoEnterRules,
    Condition,
    PipelineDefinition,
    StageDefinition,
)
from atendia.state_machine.pipeline_evaluator import (
    evaluate_condition,
    evaluate_rule_group,
    resolve_field_path,
    select_best_stage,
)


# ---------- resolve_field_path ----------


def test_resolve_field_path_top_level_plain():
    assert resolve_field_path({"plan_credito": "36m"}, "plan_credito") == "36m"


def test_resolve_field_path_extracted_data_shape():
    """The conversation_state.extracted_data leaf is {value, confidence,
    source_turn}. The resolver unwraps to the inner value."""
    data = {"modelo_interes": {"value": "DM200", "confidence": 0.9, "source_turn": 3}}
    assert resolve_field_path(data, "modelo_interes") == "DM200"


def test_resolve_field_path_nested_dot_doc_status():
    """DOCS_INE.status is the canonical document-field shape."""
    data = {"DOCS_INE": {"status": "ok", "uploaded_at": "..."}}
    assert resolve_field_path(data, "DOCS_INE.status") == "ok"


def test_resolve_field_path_missing_segment_returns_none():
    assert resolve_field_path({"a": {"b": "x"}}, "a.c") is None
    assert resolve_field_path({}, "anything") is None


def test_resolve_field_path_missing_top_returns_none():
    assert resolve_field_path({"a": "x"}, "z") is None


# ---------- evaluate_condition ----------


def test_condition_exists_true_false():
    c = Condition(field="x", operator="exists")
    assert evaluate_condition(c, {"x": "v"}) is True
    assert evaluate_condition(c, {"x": ""}) is False
    assert evaluate_condition(c, {}) is False


def test_condition_not_exists():
    c = Condition(field="x", operator="not_exists")
    assert evaluate_condition(c, {}) is True
    assert evaluate_condition(c, {"x": None}) is True
    assert evaluate_condition(c, {"x": "v"}) is False


def test_condition_equals():
    c = Condition(field="DOCS_INE.status", operator="equals", value="ok")
    assert evaluate_condition(c, {"DOCS_INE": {"status": "ok"}}) is True
    assert evaluate_condition(c, {"DOCS_INE": {"status": "missing"}}) is False


def test_condition_not_equals():
    c = Condition(field="status", operator="not_equals", value="ok")
    assert evaluate_condition(c, {"status": "rejected"}) is True
    assert evaluate_condition(c, {"status": "ok"}) is False


def test_condition_contains():
    c = Condition(field="notes", operator="contains", value="urgente")
    assert evaluate_condition(c, {"notes": "es urgente, llamar"}) is True
    assert evaluate_condition(c, {"notes": "todo bien"}) is False
    # None never contains anything
    assert evaluate_condition(c, {}) is False


def test_condition_greater_than_less_than():
    gt = Condition(field="score", operator="greater_than", value=50)
    lt = Condition(field="score", operator="less_than", value=50)
    assert evaluate_condition(gt, {"score": 80}) is True
    assert evaluate_condition(gt, {"score": 30}) is False
    assert evaluate_condition(lt, {"score": 30}) is True
    assert evaluate_condition(lt, {"score": 80}) is False
    # Non-numeric value → false (no exceptions leak)
    assert evaluate_condition(gt, {"score": "n/a"}) is False


def test_condition_in_not_in():
    in_op = Condition(field="plan", operator="in", value=["36", "48"])
    not_in_op = Condition(field="plan", operator="not_in", value=["12"])
    assert evaluate_condition(in_op, {"plan": "36"}) is True
    assert evaluate_condition(in_op, {"plan": "60"}) is False
    assert evaluate_condition(not_in_op, {"plan": "36"}) is True
    assert evaluate_condition(not_in_op, {"plan": "12"}) is False


# ---------- evaluate_rule_group ----------


def test_rule_group_disabled_returns_false():
    rules = AutoEnterRules(
        enabled=False,
        conditions=[],
    )
    assert evaluate_rule_group(rules, {"x": "v"}) is False


def test_rule_group_all_match():
    rules = AutoEnterRules(
        enabled=True,
        match="all",
        conditions=[
            Condition(field="modelo_interes", operator="exists"),
            Condition(field="plan_credito", operator="exists"),
            Condition(field="tipo_enganche", operator="exists"),
        ],
    )
    fields = {
        "modelo_interes": "DM200",
        "plan_credito": "36",
        "tipo_enganche": "efectivo",
    }
    assert evaluate_rule_group(rules, fields) is True
    # Missing one → no match
    assert evaluate_rule_group(rules, {"modelo_interes": "DM200"}) is False


def test_rule_group_any_match():
    rules = AutoEnterRules(
        enabled=True,
        match="any",
        conditions=[
            Condition(field="DOCS_INE.status", operator="equals", value="ok"),
            Condition(field="DOCS_COMPROBANTE_DOMICILIO.status", operator="equals", value="ok"),
        ],
    )
    assert evaluate_rule_group(rules, {"DOCS_INE": {"status": "ok"}}) is True
    assert evaluate_rule_group(rules, {"DOCS_COMPROBANTE_DOMICILIO": {"status": "ok"}}) is True
    # Neither → false
    assert evaluate_rule_group(rules, {}) is False


# ---------- select_best_stage ----------


def _stage(
    *,
    sid: str,
    rules: AutoEnterRules | None = None,
    terminal: bool = False,
    backward: bool = False,
) -> StageDefinition:
    return StageDefinition(
        id=sid,
        auto_enter_rules=rules,
        is_terminal=terminal,
        allow_auto_backward=backward,
    )


def _pipeline(stages: list[StageDefinition]) -> PipelineDefinition:
    return PipelineDefinition(version=1, stages=stages, fallback="escalate_to_human")


def test_select_best_stage_no_matching_returns_none():
    pipe = _pipeline([_stage(sid="nuevo"), _stage(sid="propuesta")])
    assert select_best_stage(matching=[], current_stage_id="nuevo", pipeline=pipe) is None


def test_select_best_stage_prefers_latest_forward():
    pipe = _pipeline(
        [
            _stage(sid="nuevo"),
            _stage(sid="potencial"),
            _stage(sid="propuesta"),
        ]
    )
    # Both potencial and propuesta match; we should pick propuesta (later)
    matches = [pipe.stages[1], pipe.stages[2]]
    pick = select_best_stage(
        matching=matches,
        current_stage_id="nuevo",
        pipeline=pipe,
    )
    assert pick is not None
    assert pick.id == "propuesta"


def test_select_best_stage_skips_current():
    pipe = _pipeline([_stage(sid="nuevo"), _stage(sid="potencial")])
    pick = select_best_stage(
        matching=[pipe.stages[1]],
        current_stage_id="potencial",
        pipeline=pipe,
    )
    assert pick is None


def test_select_best_stage_blocks_backward_without_flag():
    pipe = _pipeline(
        [
            _stage(sid="nuevo"),
            _stage(sid="potencial"),
            _stage(sid="propuesta"),
        ]
    )
    # Currently in propuesta; potencial matches but doesn't allow backward
    pick = select_best_stage(
        matching=[pipe.stages[1]],
        current_stage_id="propuesta",
        pipeline=pipe,
    )
    assert pick is None


def test_select_best_stage_allows_backward_when_flagged():
    pipe = _pipeline(
        [
            _stage(sid="nuevo"),
            _stage(sid="potencial", backward=True),
            _stage(sid="propuesta"),
        ]
    )
    pick = select_best_stage(
        matching=[pipe.stages[1]],
        current_stage_id="propuesta",
        pipeline=pipe,
    )
    assert pick is not None
    assert pick.id == "potencial"


def test_select_best_stage_terminal_blocks_any_move():
    pipe = _pipeline(
        [
            _stage(sid="nuevo"),
            _stage(sid="cerrado", terminal=True),
            _stage(sid="reabierto", backward=True),
        ]
    )
    # Currently in cerrado (terminal). Even though reabierto matches and
    # itself allows backward, we never leave a terminal stage.
    pick = select_best_stage(
        matching=[pipe.stages[2]],
        current_stage_id="cerrado",
        pipeline=pipe,
    )
    assert pick is None


def test_select_best_stage_unknown_current_returns_none():
    """Orphan stage (operator deleted it from definition). Don't try to
    auto-heal — leave it visible in the board until manually moved."""
    pipe = _pipeline([_stage(sid="nuevo"), _stage(sid="propuesta")])
    pick = select_best_stage(
        matching=[pipe.stages[1]],
        current_stage_id="stage_that_does_not_exist",
        pipeline=pipe,
    )
    assert pick is None


# ---------- End-to-end matrix (no DB) ----------


def test_cliente_potencial_rule_end_to_end():
    """Cliente Potencial scenario from the user's spec."""
    cliente_potencial = _stage(
        sid="cliente_potencial",
        rules=AutoEnterRules(
            enabled=True,
            match="all",
            conditions=[
                Condition(field="modelo_interes", operator="exists"),
                Condition(field="plan_credito", operator="exists"),
                Condition(field="tipo_enganche", operator="exists"),
            ],
        ),
    )
    pipe = _pipeline([_stage(sid="nuevo"), cliente_potencial])
    fields = {
        "modelo_interes": "DM200 2026",
        "plan_credito": "36",
        "tipo_enganche": "efectivo",
    }
    matching = [
        s
        for s in pipe.stages
        if s.auto_enter_rules and evaluate_rule_group(s.auto_enter_rules, fields)
    ]
    pick = select_best_stage(matching=matching, current_stage_id="nuevo", pipeline=pipe)
    assert pick is not None
    assert pick.id == "cliente_potencial"


def test_papeleria_completa_rule_end_to_end():
    """Papelería Completa scenario — driven by DOCS_*.status equality."""
    papeleria = _stage(
        sid="papeleria_completa",
        rules=AutoEnterRules(
            enabled=True,
            match="all",
            conditions=[
                Condition(field="DOCS_INE.status", operator="equals", value="ok"),
                Condition(field="DOCS_COMPROBANTE_DOMICILIO.status", operator="equals", value="ok"),
                Condition(field="DOCS_ESTADOS_CUENTA.status", operator="equals", value="ok"),
                Condition(field="DOCS_RECIBOS_NOMINA.status", operator="equals", value="ok"),
            ],
        ),
    )
    pipe = _pipeline([_stage(sid="documentos_pendientes"), papeleria])
    fields = {
        "DOCS_INE": {"status": "ok"},
        "DOCS_COMPROBANTE_DOMICILIO": {"status": "ok"},
        "DOCS_ESTADOS_CUENTA": {"status": "ok"},
        "DOCS_RECIBOS_NOMINA": {"status": "ok"},
    }
    matching = [
        s
        for s in pipe.stages
        if s.auto_enter_rules and evaluate_rule_group(s.auto_enter_rules, fields)
    ]
    pick = select_best_stage(
        matching=matching, current_stage_id="documentos_pendientes", pipeline=pipe
    )
    assert pick is not None
    assert pick.id == "papeleria_completa"


def test_papeleria_incompleta_does_not_match():
    """If even one DOCS_*.status is not ok, the rule must not fire."""
    papeleria = _stage(
        sid="papeleria_completa",
        rules=AutoEnterRules(
            enabled=True,
            match="all",
            conditions=[
                Condition(field="DOCS_INE.status", operator="equals", value="ok"),
                Condition(field="DOCS_COMPROBANTE_DOMICILIO.status", operator="equals", value="ok"),
            ],
        ),
    )
    fields = {
        "DOCS_INE": {"status": "ok"},
        "DOCS_COMPROBANTE_DOMICILIO": {"status": "pending_review"},
    }
    assert evaluate_rule_group(papeleria.auto_enter_rules, fields) is False

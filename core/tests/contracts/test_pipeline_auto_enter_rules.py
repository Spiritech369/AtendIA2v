"""Contract tests for auto_enter_rules (M1 of the pipeline-automation plan).

These pin the schema the evaluator (M3) and the rule builder UI (M2) will
both rely on. If any of these tests change shape, both sides break and we
notice in CI instead of in production.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atendia.contracts.pipeline_definition import (
    OPERATORS,
    AutoEnterRules,
    Condition,
    PipelineDefinition,
    StageDefinition,
)

# ---------- Condition ----------


def test_condition_exists_no_value_ok():
    c = Condition(field="modelo_interes", operator="exists")
    assert c.value is None


def test_condition_exists_with_value_rejected():
    with pytest.raises(ValidationError, match="does not accept a value"):
        Condition(field="modelo_interes", operator="exists", value="anything")


def test_condition_equals_requires_value():
    with pytest.raises(ValidationError, match="requires a value"):
        Condition(field="plan_credito", operator="equals")


def test_condition_in_requires_list_value():
    with pytest.raises(ValidationError, match="requires a list value"):
        Condition(field="plan_credito", operator="in", value="36")
    c = Condition(field="plan_credito", operator="in", value=["36", "48"])
    assert c.value == ["36", "48"]


def test_condition_dot_path_field_accepted():
    """DOCS_INE.status is the canonical document-status form."""
    c = Condition(field="DOCS_INE.status", operator="equals", value="ok")
    assert c.field == "DOCS_INE.status"


def test_condition_rejects_garbage_field():
    with pytest.raises(ValidationError, match="must be dot-separated"):
        Condition(field="not a valid field!", operator="exists")
    with pytest.raises(ValidationError, match="must be dot-separated"):
        Condition(field=".leading.dot", operator="exists")
    with pytest.raises(ValidationError, match="must be dot-separated"):
        Condition(field="trailing.dot.", operator="exists")


def test_condition_unknown_operator_rejected():
    with pytest.raises(ValidationError):
        Condition(field="x", operator="exists_lol", value=None)


def test_condition_extra_field_forbidden():
    """The spec is closed; reject unknown keys so typos surface."""
    with pytest.raises(ValidationError):
        Condition(field="x", operator="exists", banana="yes")


def test_operators_constant_in_lockstep_with_literal():
    """OPERATORS is exported for the FE to import via codegen later. Pin
    that the runtime constant matches what Condition accepts."""
    assert OPERATORS == {
        "exists",
        "not_exists",
        "equals",
        "not_equals",
        "contains",
        "greater_than",
        "less_than",
        "in",
        "not_in",
    }


# ---------- AutoEnterRules ----------


def test_auto_enter_rules_disabled_empty_ok():
    rules = AutoEnterRules()
    assert rules.enabled is False
    assert rules.conditions == []


def test_auto_enter_rules_enabled_empty_rejected():
    """A stage with auto-enter on and no conditions would match anything —
    a classic 'silently-active' authoring bug. Reject upfront."""
    with pytest.raises(ValidationError, match="at least one condition"):
        AutoEnterRules(enabled=True)


def test_auto_enter_rules_round_trip():
    rules = AutoEnterRules(
        enabled=True,
        match="all",
        conditions=[
            Condition(field="modelo_interes", operator="exists"),
            Condition(field="plan_credito", operator="exists"),
            Condition(field="tipo_enganche", operator="exists"),
        ],
    )
    dumped = rules.model_dump()
    parsed = AutoEnterRules.model_validate(dumped)
    assert parsed == rules


def test_auto_enter_rules_match_any_accepted():
    rules = AutoEnterRules(
        enabled=True,
        match="any",
        conditions=[Condition(field="x", operator="exists")],
    )
    assert rules.match == "any"


def test_auto_enter_rules_match_invalid_rejected():
    with pytest.raises(ValidationError):
        AutoEnterRules(
            enabled=True,
            match="every",  # not in {"all", "any"}
            conditions=[Condition(field="x", operator="exists")],
        )


# ---------- StageDefinition with rules ----------


def test_stage_definition_with_auto_enter_rules():
    stage = StageDefinition(
        id="cliente_potencial",
        auto_enter_rules=AutoEnterRules(
            enabled=True,
            conditions=[
                Condition(field="modelo_interes", operator="exists"),
                Condition(field="plan_credito", operator="exists"),
                Condition(field="tipo_enganche", operator="exists"),
            ],
        ),
    )
    assert stage.auto_enter_rules is not None
    assert len(stage.auto_enter_rules.conditions) == 3


def test_stage_definition_terminal_cannot_allow_backward():
    """Terminal + allow_auto_backward is conceptually contradictory."""
    with pytest.raises(ValidationError, match="incompatible"):
        StageDefinition(
            id="cerrado",
            is_terminal=True,
            allow_auto_backward=True,
        )


def test_stage_definition_terminal_alone_ok():
    s = StageDefinition(id="cerrado", is_terminal=True)
    assert s.is_terminal is True
    assert s.allow_auto_backward is False


def test_stage_definition_allows_extra_presentation_keys():
    """Existing pipelines store color/label in JSONB; the contract must
    not reject them. M1 surfaces is_terminal/allow_auto_backward as
    typed fields but keeps extra='allow' for presentation noise."""
    s = StageDefinition.model_validate(
        {
            "id": "nuevo",
            "color": "#6366f1",
            "label": "Nuevo lead",
            "timeout_hours": 24,
        }
    )
    assert s.id == "nuevo"


# ---------- PipelineDefinition round-trip ----------


def test_pipeline_with_rules_round_trip():
    """Spec example: 'Cliente Potencial' rule from the user's prompt."""
    raw = {
        "version": 1,
        "fallback": "escalate_to_human",
        "stages": [
            {"id": "nuevo", "transitions": []},
            {
                "id": "cliente_potencial",
                "is_terminal": False,
                "allow_auto_backward": False,
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "modelo_interes", "operator": "exists"},
                        {"field": "plan_credito", "operator": "exists"},
                        {"field": "tipo_enganche", "operator": "exists"},
                    ],
                },
                "transitions": [],
            },
        ],
    }
    p = PipelineDefinition.model_validate(raw)
    assert p.stages[1].auto_enter_rules is not None
    assert p.stages[1].auto_enter_rules.enabled is True
    # Round-trip
    dumped = p.model_dump(exclude_none=True)
    again = PipelineDefinition.model_validate(dumped)
    assert again.stages[1].auto_enter_rules == p.stages[1].auto_enter_rules


def test_pipeline_papeleria_completa_doc_rules():
    """Spec example: 'Papelería completa' driven by document statuses."""
    raw = {
        "version": 1,
        "fallback": "escalate_to_human",
        "stages": [
            {
                "id": "papeleria_completa",
                "auto_enter_rules": {
                    "enabled": True,
                    "match": "all",
                    "conditions": [
                        {"field": "DOCS_INE.status", "operator": "equals", "value": "ok"},
                        {
                            "field": "DOCS_COMPROBANTE_DOMICILIO.status",
                            "operator": "equals",
                            "value": "ok",
                        },
                        {
                            "field": "DOCS_ESTADOS_CUENTA.status",
                            "operator": "equals",
                            "value": "ok",
                        },
                        {
                            "field": "DOCS_RECIBOS_NOMINA.status",
                            "operator": "equals",
                            "value": "ok",
                        },
                    ],
                },
                "transitions": [],
            },
        ],
    }
    p = PipelineDefinition.model_validate(raw)
    fields = [c.field for c in p.stages[0].auto_enter_rules.conditions]
    assert fields == [
        "DOCS_INE.status",
        "DOCS_COMPROBANTE_DOMICILIO.status",
        "DOCS_ESTADOS_CUENTA.status",
        "DOCS_RECIBOS_NOMINA.status",
    ]

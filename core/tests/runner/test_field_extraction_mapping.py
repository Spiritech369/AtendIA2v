"""Tests for decide_action — pure decision logic for AI → attrs flow.

The decision rules are documented in
docs/plans/2026-05-13-ai-field-extraction-design.md.
"""
from atendia.runner.field_extraction_mapping import (
    Action,
    decide_action,
    map_entity_to_attr,
)


def test_map_entity_to_attr_known():
    assert map_entity_to_attr("brand") == "marca"
    assert map_entity_to_attr("modelo_interes") == "modelo_interes"
    assert map_entity_to_attr("plan") == "plan_credito"


def test_map_entity_to_attr_unknown_returns_none():
    assert map_entity_to_attr("random_thing") is None


def test_decide_auto_when_empty_attr_and_high_confidence():
    assert decide_action(current_value=None, new_value="Honda", confidence=0.92) == Action.AUTO
    assert decide_action(current_value="", new_value="Honda", confidence=0.85) == Action.AUTO


def test_decide_suggest_when_empty_and_medium_confidence():
    assert decide_action(current_value=None, new_value="Honda", confidence=0.70) == Action.SUGGEST
    assert decide_action(current_value=None, new_value="Honda", confidence=0.60) == Action.SUGGEST


def test_decide_skip_when_low_confidence():
    assert decide_action(current_value=None, new_value="Honda", confidence=0.59) == Action.SKIP
    assert decide_action(current_value=None, new_value="Honda", confidence=0.0) == Action.SKIP


def test_decide_noop_when_values_match():
    assert decide_action(current_value="Honda", new_value="Honda", confidence=0.99) == Action.NOOP


def test_decide_noop_handles_string_number_equality():
    """NLU often returns numbers as int; attrs JSONB stores as string. Compare normalized."""
    assert decide_action(current_value="10", new_value=10, confidence=0.95) == Action.NOOP
    assert decide_action(current_value=10, new_value="10", confidence=0.95) == Action.NOOP


def test_decide_suggest_when_existing_differs_high_confidence():
    """Never overwrite an existing value without human approval — even at 0.95."""
    assert decide_action(current_value="Honda", new_value="Yamaha", confidence=0.95) == Action.SUGGEST


def test_decide_suggest_when_existing_differs_medium_confidence():
    assert decide_action(current_value="Honda", new_value="Yamaha", confidence=0.70) == Action.SUGGEST


def test_decide_skip_when_existing_differs_low_confidence():
    """If we wouldn't even suggest on an empty field, don't bother the operator."""
    assert decide_action(current_value="Honda", new_value="Yamaha", confidence=0.40) == Action.SKIP


def test_decide_skip_when_new_value_is_empty():
    assert decide_action(current_value=None, new_value=None, confidence=0.95) == Action.SKIP
    assert decide_action(current_value=None, new_value="", confidence=0.95) == Action.SKIP

"""W6/W8 — validate_definition enforces per-type config for the two
new node types (trigger_workflow and ask_question).

* trigger_workflow needs config.target_workflow_id (UUID string).
* ask_question needs config.question (non-empty str) AND
  config.variable (slug-y identifier).
"""

from __future__ import annotations

import pytest

from atendia.workflows.engine import WorkflowValidationError, validate_definition


def _wrap_node(node: dict, edges: list[dict] | None = None) -> dict:
    """Wrap a single node in a minimal valid workflow definition."""
    return {
        "nodes": [
            {"id": "start", "type": "trigger", "config": {}},
            node,
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": node["id"]},
            {"from": node["id"], "to": "end"},
            *(edges or []),
        ],
    }


def test_trigger_workflow_node_requires_target_workflow_id():
    bad = _wrap_node({"id": "trig", "type": "trigger_workflow", "config": {}})
    with pytest.raises(WorkflowValidationError) as exc:
        validate_definition(bad)
    assert "target_workflow_id" in str(exc.value).lower()


def test_trigger_workflow_node_rejects_non_uuid_target():
    bad = _wrap_node(
        {
            "id": "trig",
            "type": "trigger_workflow",
            "config": {"target_workflow_id": "not-a-uuid"},
        }
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_definition(bad)
    assert "target_workflow_id" in str(exc.value).lower()


def test_trigger_workflow_node_accepts_valid_uuid():
    """Happy path: a well-formed trigger_workflow node passes
    validation. (Whether the target workflow EXISTS is a runtime
    concern — validate_definition is structural.)"""
    from uuid import uuid4

    ok = _wrap_node(
        {
            "id": "trig",
            "type": "trigger_workflow",
            "config": {"target_workflow_id": str(uuid4())},
        }
    )
    # No raise = pass
    validate_definition(ok)


def test_ask_question_node_requires_question():
    bad = _wrap_node(
        {
            "id": "ask",
            "type": "ask_question",
            "config": {"variable": "email"},  # missing question
        }
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_definition(bad)
    assert "question" in str(exc.value).lower()


def test_ask_question_node_requires_variable():
    bad = _wrap_node(
        {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "¿cuál es tu email?"},  # missing variable
        }
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_definition(bad)
    assert "variable" in str(exc.value).lower()


def test_ask_question_node_rejects_invalid_variable_name():
    """Variable names must be slug-style (alphanumeric + underscore,
    no spaces, doesn't start with a digit)."""
    bad = _wrap_node(
        {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "¿tu email?", "variable": "has space"},
        }
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_definition(bad)
    assert "variable" in str(exc.value).lower()


def test_ask_question_node_accepts_valid_config():
    ok = _wrap_node(
        {
            "id": "ask",
            "type": "ask_question",
            "config": {"question": "¿cuál es tu email?", "variable": "email"},
        }
    )
    # No raise = pass
    validate_definition(ok)

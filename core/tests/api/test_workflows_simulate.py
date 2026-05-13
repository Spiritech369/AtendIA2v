"""Dry-run simulation: walks the actual graph, no fabricated data.

Before this rewrite the simulate endpoint always returned ``activated_nodes
= nodes[:6]`` and a hardcoded "¡Hola Juan!" response regardless of what
the workflow actually contained. That made the feature dishonest and gave
operators no real preview of what their workflow would do.

These tests pin the new contract: traversal follows ``edges``, variables
flow through ``update_field`` nodes into message substitution, conditions
prefer the ``true`` branch with a warning, and the simulator stops at
``end`` nodes or dead-ends without faking downstream actions.
"""
from __future__ import annotations

from atendia.api.workflows_routes import _dry_run_workflow


def _trigger_node() -> dict:
    return {"id": "t1", "type": "trigger", "config": {"event": "message_received"}}


def test_empty_workflow_warns_no_trigger():
    out = _dry_run_workflow({"nodes": [], "edges": []}, "hola")
    assert out["activated_nodes"] == []
    assert out["generated_response"] == ""
    assert any("disparador" in w.lower() for w in out["warnings"])


def test_linear_trigger_to_message_to_end():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "m1", "type": "message", "config": {"text": "Hola, gracias."}},
            {"id": "e1", "type": "end", "config": {}},
        ],
        "edges": [
            {"from": "t1", "to": "m1"},
            {"from": "m1", "to": "e1"},
        ],
    }
    out = _dry_run_workflow(definition, "quiero info")
    assert out["activated_nodes"] == ["t1", "m1", "e1"]
    assert out["generated_response"] == "Hola, gracias."
    assert out["assigned_advisor"] is None
    assert out["created_tasks"] == []


def test_update_field_then_message_substitutes_variable():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "u1", "type": "update_field", "config": {"field": "nombre", "value": "Pedro"}},
            {"id": "m1", "type": "message", "config": {"text": "Hola {{nombre}}, ¿qué tal?"}},
        ],
        "edges": [
            {"from": "t1", "to": "u1"},
            {"from": "u1", "to": "m1"},
        ],
    }
    out = _dry_run_workflow(definition, "")
    assert out["variables_saved"]["nombre"] == "Pedro"
    assert out["generated_response"] == "Hola Pedro, ¿qué tal?"


def test_unsubstituted_variable_left_as_placeholder():
    """Honesty: if the variable isn't set, leave the placeholder visible
    instead of guessing a fake value."""
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "m1", "type": "message", "config": {"text": "Hola {{nombre}}"}},
        ],
        "edges": [{"from": "t1", "to": "m1"}],
    }
    out = _dry_run_workflow(definition, "")
    assert out["generated_response"] == "Hola {{nombre}}"


def test_condition_prefers_true_branch_and_warns():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "c1", "type": "condition", "config": {"field": "extracted.x", "operator": "exists"}},
            {"id": "m_yes", "type": "message", "config": {"text": "Sí"}},
            {"id": "m_no", "type": "message", "config": {"text": "No"}},
        ],
        "edges": [
            {"from": "t1", "to": "c1"},
            {"from": "c1", "to": "m_yes", "label": "true"},
            {"from": "c1", "to": "m_no", "label": "false"},
        ],
    }
    out = _dry_run_workflow(definition, "")
    assert "m_yes" in out["activated_nodes"]
    assert "m_no" not in out["activated_nodes"]
    assert out["generated_response"] == "Sí"
    assert any("rama" in w.lower() and "sí" in w.lower() for w in out["warnings"])


def test_assign_agent_populates_assigned_advisor():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "a1", "type": "assign_agent", "config": {"agent_id": "agent-xyz"}},
        ],
        "edges": [{"from": "t1", "to": "a1"}],
    }
    out = _dry_run_workflow(definition, "")
    assert out["assigned_advisor"] == "agent-xyz"


def test_create_task_appears_in_created_tasks():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "k1", "type": "create_task", "config": {"label": "Llamar al cliente"}},
            {"id": "k2", "type": "followup", "config": {"title": "Mandar cotización"}},
        ],
        "edges": [
            {"from": "t1", "to": "k1"},
            {"from": "k1", "to": "k2"},
        ],
    }
    out = _dry_run_workflow(definition, "")
    assert out["created_tasks"] == ["Llamar al cliente", "Mandar cotización"]


def test_delay_emits_warning_but_continues():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "d1", "type": "delay", "config": {"seconds": 60}},
            {"id": "m1", "type": "message", "config": {"text": "luego"}},
        ],
        "edges": [
            {"from": "t1", "to": "d1"},
            {"from": "d1", "to": "m1"},
        ],
    }
    out = _dry_run_workflow(definition, "")
    assert "d1" in out["activated_nodes"]
    assert "m1" in out["activated_nodes"]
    assert any("delay" in w.lower() or "pausaría" in w.lower() for w in out["warnings"])


def test_cycle_detected_and_terminated():
    """Edges from `delay` nodes don't count as cycles in the engine, but they
    do in dry-run because we don't actually wait — without protection we'd
    spin forever. Make sure the traversal terminates."""
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "m1", "type": "message", "config": {"text": "loop"}},
        ],
        "edges": [
            {"from": "t1", "to": "m1"},
            {"from": "m1", "to": "t1"},  # back-edge
        ],
    }
    out = _dry_run_workflow(definition, "")
    assert any("bucle" in w.lower() for w in out["warnings"])


def test_end_node_stops_traversal_even_with_outgoing_edges():
    definition = {
        "nodes": [
            _trigger_node(),
            {"id": "e1", "type": "end", "config": {}},
            {"id": "m1", "type": "message", "config": {"text": "no debería"}},
        ],
        "edges": [
            {"from": "t1", "to": "e1"},
            {"from": "e1", "to": "m1"},
        ],
    }
    out = _dry_run_workflow(definition, "")
    assert out["activated_nodes"] == ["t1", "e1"]
    assert out["generated_response"] == ""

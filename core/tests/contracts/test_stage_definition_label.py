"""Wave1 — StageDefinition.label is an explicit optional field.

Before this fix, label was only accessible when the JSONB pipeline
definition happened to include it (extra='allow'). Programmatic /
default / fixture pipelines that omitted label crashed any code
doing stage.label with AttributeError. This was the root cause of
2 long-standing runner test failures."""

from __future__ import annotations

from atendia.contracts.pipeline_definition import StageDefinition


def test_stage_definition_label_defaults_to_none_when_absent():
    """A stage built without a label must NOT raise AttributeError on
    .label — it returns None."""
    stage = StageDefinition(id="nuevo")
    assert stage.label is None  # the bug made this raise AttributeError


def test_stage_definition_label_preserved_when_present():
    """When the JSONB carries label, it's preserved."""
    stage = StageDefinition(id="nuevo", label="Nuevo")
    assert stage.label == "Nuevo"


def test_stage_definition_label_or_id_fallback_pattern():
    """The canonical call-site pattern `stage.label or stage.id`
    yields the id when label is absent (used in handoff summaries +
    stage-transition system events)."""
    stage = StageDefinition(id="escalado")
    assert (stage.label or stage.id) == "escalado"
    stage2 = StageDefinition(id="escalado", label="Escalado a humano")
    assert (stage2.label or stage2.id) == "Escalado a humano"

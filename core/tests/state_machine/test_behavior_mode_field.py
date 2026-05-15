"""Fase 6 — StageDefinition.behavior_mode opt-in field.

These tests cover the contract layer (validation) and the seed
(motos pipeline pins modes for each stage). The runner-level override
is exercised in Fase 7's e2e walk-through.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
)
from atendia.state_machine.motos_credito_pipeline import (
    MOTOS_CREDITO_PIPELINE_DEFINITION,
)


def test_behavior_mode_defaults_to_none():
    """Backwards compat: stages without explicit behavior_mode keep the
    legacy router-driven behaviour (no override)."""
    stage = StageDefinition(id="nuevo", actions_allowed=["greet"])
    assert stage.behavior_mode is None


@pytest.mark.parametrize("mode", [m.value for m in FlowMode])
def test_behavior_mode_accepts_every_flow_mode(mode: str):
    stage = StageDefinition(
        id="nuevo",
        actions_allowed=["greet"],
        behavior_mode=mode,
    )
    assert stage.behavior_mode == mode


def test_behavior_mode_rejects_unknown_value():
    """Typos in JSONB shouldn't be tolerated — the validator must catch
    them at pipeline load time, not silently fall through to SUPPORT."""
    with pytest.raises(ValidationError) as exc:
        StageDefinition(
            id="nuevo",
            actions_allowed=["greet"],
            behavior_mode="NOPE",
        )
    assert "behavior_mode" in str(exc.value)


def test_motos_seed_pins_behavior_mode_for_funnel_stages():
    """The seed assigns a deliberate behavior_mode for each non-terminal
    stage. Drifting this matrix changes how the composer prompts; lock
    it down so accidental edits surface in the diff."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    expected = {
        "nuevo_lead": "PLAN",
        "calificacion_inicial": "PLAN",
        "plan_seleccionado": "PLAN",
        "papeleria_incompleta": "DOC",
    }
    for stage in pipeline.stages:
        if stage.id in expected:
            assert stage.behavior_mode == expected[stage.id], (
                f"stage {stage.id} should pin behavior_mode={expected[stage.id]} "
                f"but got {stage.behavior_mode}"
            )

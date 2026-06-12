from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from atendia.scripts import seed_dinamo_phase_d_workflows as phase_d
from atendia.scripts.seed_dinamo_v1 import PLAN_CREDITO_CHOICES, PLAN_ENGANCHE_BY_PLAN


def test_phase_d_targets_only_core_workflows() -> None:
    assert phase_d.PHASE_D_CORE_WORKFLOWS == (
        "state.write_contact_field",
        "pipeline.transition",
        "handoff.start",
        "human.assign",
        "notification.create",
    )
    assert set(phase_d._phase_d_specs()) == set(phase_d.PHASE_D_CORE_WORKFLOWS)


def test_phase_d_definition_marks_side_effects_disabled() -> None:
    specs = phase_d._phase_d_specs()

    for key, spec in specs.items():
        definition = phase_d._phase_d_definition(spec)
        metadata = definition["metadata"]

        assert metadata["phase"] == "D"
        assert metadata["side_effects"] == "disabled"
        assert metadata["customer_visible_output_allowed"] is False
        assert metadata["workflow_key"] == key
        assert definition["nodes"]


def test_plan_enganche_derivation_preview_is_dry_run_only() -> None:
    workflow = _workflow("state.write_contact_field")
    plan = PLAN_CREDITO_CHOICES[0]

    preview = phase_d._preview_workflow(
        workflow.definition,
        {"field": "Plan_Credito", "value": plan},
    )

    assert preview["status"] == "dry_run"
    assert preview["field_updates"]["Plan_Enganche"] == PLAN_ENGANCHE_BY_PLAN[plan]
    assert preview["outbound_outbox_writes"] == 0
    assert preview["workflow_execution_writes"] == 0
    assert preview["side_effects"] == {
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }


def test_handoff_preview_assigns_notifies_pauses_without_visible_copy() -> None:
    workflow = _workflow("handoff.start")

    preview = phase_d._preview_workflow(
        workflow.definition,
        {"reason": "pago_reportado", "conversation_id": "conv-1"},
    )

    assert preview["assignments"] == [{"role": "operator", "dry_run": True}]
    assert preview["notifications"][0]["dedupe_key"] == "dinamo_handoff:conv-1"
    assert preview["pause_bot"] == {"mode": "limited", "dry_run": True}
    assert preview["field_updates"] == {
        "Handoff_Humano": "true",
        "Motivo_Handoff": "pago_reportado",
    }
    assert preview["customer_visible_output"] is None


def test_phase_d_lab_all_scenarios_pass_with_seeded_definitions() -> None:
    workflows = {key: _workflow(key) for key in phase_d.PHASE_D_CORE_WORKFLOWS}

    lab = phase_d._run_phase_d_dry_lab(workflows, phase_d.phase_d_scenarios())

    assert len(lab) == len(phase_d.phase_d_scenarios())
    assert all(result["status"] == "passed" for result in lab)
    assert all(result["send_decision"] == "no_send" for result in lab)
    assert all(result["outbound_outbox_writes"] == 0 for result in lab)
    assert all(result["workflow_execution_writes"] == 0 for result in lab)


def test_scenario_turn_includes_required_inbound_text_and_event_payload() -> None:
    scenario = phase_d.phase_d_scenarios()[0]

    turn = phase_d._scenario_turn(scenario)

    assert turn["inbound_text"] == "workflow_event:field_extracted:derive_plan_enganche"
    assert turn["event_type"] == scenario.event_type
    assert turn["event"] == scenario.event


def test_assert_preview_detects_customer_copy_and_missing_node() -> None:
    scenario = phase_d.phase_d_scenarios()[0]
    bad_preview = {
        "nodes": [],
        "field_updates": {},
        "customer_visible_output": {"blocked": True},
        "outbound_outbox_writes": 1,
        "workflow_execution_writes": 1,
    }

    failures = phase_d._assert_preview(scenario, bad_preview)

    assert "missing_node:derive_plan_enganche" in failures
    assert "customer_visible_output_present" in failures
    assert "outbox_write_present" in failures
    assert "workflow_execution_write_present" in failures


@pytest.mark.asyncio
async def test_phase_d_dry_run_preview_does_not_query_db() -> None:
    result = await phase_d.seed_dinamo_phase_d_workflows(
        object(),  # type: ignore[arg-type]
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.pass_count == len(phase_d.phase_d_scenarios())
    assert result.updated_workflows == list(phase_d.PHASE_D_CORE_WORKFLOWS)
    assert result.decision == phase_d.PHASE_D_DECISION_READY


def test_script_does_not_import_openai_or_execute_workflow_engine() -> None:
    source = Path("atendia/scripts/seed_dinamo_phase_d_workflows.py").read_text(
        encoding="utf-8"
    )

    assert "from openai" not in source
    assert "import openai" not in source
    assert "execute_workflow(" not in source
    assert "stage_outbound" not in source


def _workflow(key: str):
    spec = phase_d._phase_d_specs()[key]
    return type(
        "WorkflowRecord",
        (),
        {
            "definition": phase_d._phase_d_definition(spec),
        },
    )()

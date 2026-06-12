from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from atendia.scripts import seed_dinamo_phase_g_google as phase_g


def test_phase_g_targets_google_workflows_and_system_fields() -> None:
    assert phase_g.PHASE_G_WORKFLOWS == (
        "google_sheets.upsert_row",
        "google_drive.upload_file",
        "google_form.mark_manual",
        "notification.create",
    )
    assert phase_g.PHASE_G_SYSTEM_FIELDS == (
        "Solicitud_ID",
        "Google_Sheets_Row_ID",
        "Google_Drive_Folder_ID",
        "Google_Drive_File_IDs",
        "Formulario",
    )


def test_phase_g_specs_are_dry_run_and_do_not_require_credentials() -> None:
    specs = phase_g.phase_g_workflow_specs()

    assert set(specs) == set(phase_g.PHASE_G_WORKFLOWS)
    for spec in specs.values():
        for node in spec.nodes:
            config = node.get("config") or {}
            assert config.get("mode", "dry_run_only") == "dry_run_only"
            assert config.get("requires_credentials", False) is False


def test_phase_g_workflow_policy_keeps_google_dry_run() -> None:
    policy = phase_g._phase_g_workflow_policy({})

    assert policy["google_workflows"] == list(phase_g.PHASE_G_WORKFLOWS)
    assert policy["google_execution_mode"] == "dry_run_only"
    assert policy["google_api_real"] is False
    assert policy["google_credentials_required_for_dry_run"] is False
    assert policy["google_failure_policy"]["customer_conversation_impact"] is False


def test_phase_g_field_policy_blocks_agent_writes() -> None:
    policy = phase_g._phase_g_field_policy({"fields": []})
    by_key = {item["field_key"]: item for item in policy["fields"]}

    for field_key in phase_g.PHASE_G_SYSTEM_FIELDS:
        field = by_key[field_key]
        assert field["writable"] is False
        if field_key == "Formulario":
            assert field["write_policy"] == "system_or_human"
        else:
            assert field["write_policy"] == "system_integration_only"
        assert field["write_policy_metadata"]["blocked_for_agent"] is True
        assert field["write_policy_metadata"]["google_api_real"] is False


def test_sheets_preview_is_idempotent_by_solicitud_and_row_id() -> None:
    scenario = phase_g.phase_g_scenarios()[0]
    preview = phase_g._preview_sheets_upsert(scenario.event)

    assert preview["idempotency_key"] == "sheets:SOL-DINAMO-0001"
    assert preview["one_row_per_solicitud"] is True
    assert preview["row_id"] == "row-44"
    assert preview["google_api_call"] is False
    assert preview["field_updates"] == {"Google_Sheets_Row_ID": "row-44"}


def test_drive_preview_separates_valid_and_invalid_documents() -> None:
    scenario = next(
        item
        for item in phase_g.phase_g_scenarios()
        if item.key == "drive_valid_and_invalid_are_separated"
    )
    preview = phase_g._preview_drive_upload(scenario.event)
    placements = {item["attachment_id"]: item for item in preview["placements"]}

    assert preview["subfolders"] == list(phase_g.DRIVE_SUBFOLDERS)
    assert preview["root_folder_name"] == "528128889241_Cliente Dinamo_2026-06-12"
    assert placements["att-ok"]["target_subfolder"] == "01_aceptados"
    assert placements["att-ok"]["counts_as_received"] is True
    assert placements["att-bad"]["target_subfolder"] == "02_rechazados"
    assert placements["att-bad"]["counts_as_received"] is False
    assert preview["field_updates"]["Google_Drive_File_IDs"] == {
        "att-ok": "dry_drive_file_att-ok",
        "att-bad": "dry_drive_file_att-bad",
    }
    assert preview["google_api_call"] is False


def test_form_manual_completion_marks_formulario_without_webhook() -> None:
    scenario = next(
        item
        for item in phase_g.phase_g_scenarios()
        if item.key == "form_manual_completion_marks_field"
    )
    workflow = _workflow_for(scenario.workflow_key)
    preview = phase_g._preview_google_workflow(workflow.definition, scenario)

    assert preview["field_updates"] == {"Formulario": "completado_manual"}
    assert preview["google_api_calls"] == 0
    assert preview["credential_lookup"] is False
    assert phase_g._assert_scenario_preview(scenario, preview) == []


def test_google_failure_notifies_internally_only() -> None:
    scenario = next(
        item
        for item in phase_g.phase_g_scenarios()
        if item.key == "google_failure_notifies_without_customer_copy"
    )
    workflow = _workflow_for(scenario.workflow_key)
    preview = phase_g._preview_google_workflow(workflow.definition, scenario)

    assert len(preview["notifications"]) == 1
    assert preview["notifications"][0]["action"] == "google_sheets.upsert_row"
    assert preview["customer_visible_output"] is None
    assert preview["outbound_outbox_writes"] == 0
    assert phase_g._assert_scenario_preview(scenario, preview) == []


def test_phase_g_lab_all_scenarios_pass_without_side_effects() -> None:
    workflows = {
        key: _workflow_for(key)
        for key in phase_g.PHASE_G_WORKFLOWS
    }
    lab = phase_g._run_phase_g_dry_lab(workflows, phase_g.phase_g_scenarios())

    assert len(lab) == len(phase_g.phase_g_scenarios())
    assert all(result["status"] == "passed" for result in lab)
    assert all(result["send_decision"] == "no_send" for result in lab)
    assert all(result["outbound_outbox_writes"] == 0 for result in lab)
    assert all(result["workflow_execution_writes"] == 0 for result in lab)
    assert all(result["google_api_real"] is False for result in lab)
    assert all(result["openai_api_real"] is False for result in lab)


def test_assert_preview_detects_google_api_and_customer_copy_leaks() -> None:
    scenario = phase_g.phase_g_scenarios()[0]
    bad_preview = {
        "google_api_calls": 1,
        "credential_lookup": True,
        "customer_visible_output": "hola",
        "outbound_outbox_writes": 1,
        "workflow_execution_writes": 1,
        "field_updates": {},
        "notifications": [],
        "side_effects": {"external_apis": True},
    }

    failures = phase_g._assert_scenario_preview(scenario, bad_preview)

    assert "google_api_call_present" in failures
    assert "credential_lookup_present" in failures
    assert "customer_visible_output_present" in failures
    assert "outbox_write_present" in failures
    assert "workflow_execution_write_present" in failures
    assert "side_effect_present" in failures


def test_scenario_turn_includes_google_event_payload() -> None:
    scenario = phase_g.phase_g_scenarios()[0]
    turn = phase_g._scenario_turn(scenario)

    assert turn["inbound_text"] == (
        "google_event:google_sheets.upsert_row:sheets_upsert_idempotent_by_solicitud"
    )
    assert turn["event_type"] == "field_updated"
    assert turn["event"]["Solicitud_ID"] == "SOL-DINAMO-0001"


@pytest.mark.asyncio
async def test_phase_g_dry_run_preview_does_not_query_db() -> None:
    result = await phase_g.seed_dinamo_phase_g_google(
        object(),  # type: ignore[arg-type]
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.pass_count == len(phase_g.phase_g_scenarios())
    assert result.updated_workflows == list(phase_g.PHASE_G_WORKFLOWS)
    assert result.updated_field_permissions == list(phase_g.PHASE_G_SYSTEM_FIELDS)
    assert result.decision == phase_g.PHASE_G_DECISION_READY
    assert result.as_dict()["google_api_real"] is False


def test_script_does_not_import_google_clients_or_call_outbox_or_workflows() -> None:
    source = Path("atendia/scripts/seed_dinamo_phase_g_google.py").read_text(
        encoding="utf-8"
    )

    assert "from openai" not in source
    assert "import openai" not in source
    assert "googleapiclient" not in source
    assert "google.cloud" not in source
    assert "requests." not in source
    assert "httpx." not in source
    assert "stage_outbound" not in source
    assert "enqueue_message" not in source
    assert "execute_workflow(" not in source


class _Workflow:
    def __init__(self, definition: dict) -> None:
        self.definition = definition


def _workflow_for(key: str) -> _Workflow:
    spec = phase_g.phase_g_workflow_specs()[key]
    return _Workflow(phase_g._phase_g_definition(spec))

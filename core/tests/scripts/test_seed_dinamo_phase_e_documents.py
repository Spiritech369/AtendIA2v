from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from atendia.scripts import seed_dinamo_phase_e_documents as phase_e


def test_phase_e_targets_document_tools_and_system_fields() -> None:
    assert phase_e.PHASE_E_TOOLS == ("document.check", "expediente.evaluate")
    assert phase_e.PHASE_E_SYSTEM_FIELDS == (
        "Docs_Checklist",
        "Doc_Incompletos",
        "Doc_Completos",
    )


def test_phase_e_tool_policy_marks_document_tools_fact_only() -> None:
    policy = phase_e._phase_e_tool_policy({"bindings": [], "optional_tools": []})

    by_name = {item["tool_name"]: item for item in policy["bindings"]}

    assert set(phase_e.PHASE_E_TOOLS) <= set(by_name)
    for tool_name in phase_e.PHASE_E_TOOLS:
        binding = by_name[tool_name]
        assert binding["enabled"] is True
        assert binding["required"] is False
        assert binding["dry_run_only"] is True
        assert binding["customer_visible_output_allowed"] is False
        assert binding["vision_api_real"] is False
        assert binding["metadata"]["fact_only"] is True


def test_phase_e_field_policy_blocks_agent_writes_to_doc_fields() -> None:
    policy = phase_e._phase_e_field_policy({"fields": []})
    by_key = {item["field_key"]: item for item in policy["fields"]}

    for field_key in phase_e.PHASE_E_SYSTEM_FIELDS:
        field = by_key[field_key]
        assert field["writable"] is False
        assert field["allowed_sources"] == ["expediente.evaluate"]
        assert field["write_policy"] == "system_tool_only"
        assert field["write_policy_metadata"]["blocked_for_agent"] is True


def test_blurred_document_is_rejected_and_not_complete() -> None:
    scenario = phase_e.phase_e_scenarios()[0]
    document_check = phase_e._document_check_preview(scenario)
    expediente = phase_e._expediente_evaluate_preview(scenario, document_check)

    facts = expediente["facts"]
    assert facts["Doc_Completos"] is False
    assert facts["stage_preview"] == "papeleria_incompleta"
    assert "ine_frente" in facts["rejected_documents"]
    assert _missing_keys(facts) == {
        "ine_frente",
        "comprobante_domicilio",
        "estado_cuenta",
    }
    assert phase_e._assert_scenario_preview(scenario, expediente) == []


def test_complete_expediente_sets_doc_completos_true() -> None:
    scenario = next(
        item
        for item in phase_e.phase_e_scenarios()
        if item.key == "complete_expediente_sets_doc_completos"
    )
    document_check = phase_e._document_check_preview(scenario)
    expediente = phase_e._expediente_evaluate_preview(scenario, document_check)

    facts = expediente["facts"]
    assert facts["Doc_Completos"] is True
    assert facts["Doc_Incompletos"] == ""
    assert facts["stage_preview"] == "papeleria_completa"
    assert _missing_keys(facts) == set()
    assert phase_e._assert_scenario_preview(scenario, expediente) == []


def test_foreign_document_preview_includes_handoff_and_notification() -> None:
    scenario = next(
        item for item in phase_e.phase_e_scenarios() if item.key == "foreign_document_doubt_handoff"
    )
    lab = phase_e._run_phase_e_dry_lab((scenario,))
    result = lab[0]

    assert result["status"] == "passed"
    previews = result["workflow_event_previews"]
    assert any(
        item["binding_name"] == "handoff.start"
        and item["reason"] == "documento_dudoso"
        for item in previews
    )
    assert any(item["binding_name"] == "notification.create" for item in previews)
    assert all(item["dry_run"] is True for item in previews)


def test_phase_e_lab_all_scenarios_pass_without_side_effects() -> None:
    lab = phase_e._run_phase_e_dry_lab(phase_e.phase_e_scenarios())

    assert len(lab) == len(phase_e.phase_e_scenarios())
    assert all(result["status"] == "passed" for result in lab)
    assert all(result["send_decision"] == "no_send" for result in lab)
    assert all(result["outbound_outbox_writes"] == 0 for result in lab)
    assert all(result["workflow_execution_writes"] == 0 for result in lab)
    assert all(result["vision_api_real"] is False for result in lab)
    assert all(result["openai_api_real"] is False for result in lab)


def test_assert_preview_detects_missing_doc_field_and_wrong_owner() -> None:
    scenario = phase_e.phase_e_scenarios()[0]
    bad_expediente = {
        "facts": {"Doc_Completos": True, "stage_preview": "papeleria_completa"},
        "field_updates": [
            {"field_key": "Docs_Checklist", "write_owner": "agent"},
            {"field_key": "Doc_Incompletos", "write_owner": "system_tool"},
        ],
    }

    failures = phase_e._assert_scenario_preview(scenario, bad_expediente)

    assert "doc_completos_mismatch" in failures
    assert "stage_preview_mismatch" in failures
    assert "field_not_system_tool:Docs_Checklist" in failures
    assert "missing_field_update:Doc_Completos" in failures


def test_scenario_turn_includes_required_inbound_text_and_attachments() -> None:
    scenario = phase_e.phase_e_scenarios()[0]

    turn = phase_e._scenario_turn(scenario)

    assert turn["inbound_text"] == "document_event:blurred_document_rejected"
    assert turn["attachments"][0]["attachment_id"] == "att-blur"
    assert turn["attachments"][0]["document_type"] == "ine_frente"


@pytest.mark.asyncio
async def test_phase_e_dry_run_preview_does_not_query_db() -> None:
    result = await phase_e.seed_dinamo_phase_e_documents(
        object(),  # type: ignore[arg-type]
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.pass_count == len(phase_e.phase_e_scenarios())
    assert result.updated_tool_bindings == list(phase_e.PHASE_E_TOOLS)
    assert result.updated_field_permissions == list(phase_e.PHASE_E_SYSTEM_FIELDS)
    assert result.decision == phase_e.PHASE_E_DECISION_READY


def test_script_does_not_import_openai_or_call_vision_or_outbox() -> None:
    source = Path("atendia/scripts/seed_dinamo_phase_e_documents.py").read_text(
        encoding="utf-8"
    )

    assert "from openai" not in source
    assert "import openai" not in source
    assert "analyze_document_media(" not in source
    assert "stage_outbound" not in source
    assert "execute_workflow(" not in source


def _missing_keys(facts: dict) -> set[str]:
    return {
        str(item.get("key"))
        for item in facts["missing_documents"]
        if isinstance(item, dict)
    }

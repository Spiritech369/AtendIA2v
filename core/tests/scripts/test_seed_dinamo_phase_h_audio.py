from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from atendia.scripts import seed_dinamo_phase_h_audio as phase_h


def test_phase_h_targets_audio_workflows_template_and_system_field() -> None:
    assert phase_h.PHASE_H_WORKFLOWS == (
        "audio.transcribe",
        "customer_message.request",
        "notification.create",
    )
    assert phase_h.PHASE_H_SYSTEM_FIELDS == ("Transcripcion_Ultimo_Audio",)
    assert phase_h.PHASE_H_TEMPLATES == ("dinamo_audio_processed_v1",)


def test_phase_h_specs_are_dry_run_and_do_not_require_credentials() -> None:
    specs = phase_h.phase_h_workflow_specs()

    assert set(specs) == set(phase_h.PHASE_H_WORKFLOWS)
    audio_node = specs["audio.transcribe"].nodes[0]
    assert audio_node["type"] == "audio_transcribe"
    assert audio_node["config"]["mode"] == "dry_run_only"
    assert audio_node["config"]["requires_credentials"] is False
    assert audio_node["config"]["low_confidence_threshold"] == 0.7


def test_phase_h_workflow_policy_keeps_audio_dry_run() -> None:
    policy = phase_h._phase_h_workflow_policy({})

    assert policy["audio_workflows"] == list(phase_h.PHASE_H_WORKFLOWS)
    assert policy["audio_execution_mode"] == "dry_run_only"
    assert policy["speech_api_real"] is False
    assert policy["audio_credentials_required_for_dry_run"] is False
    assert policy["audio_policy"]["max_next_questions"] == 1


def test_phase_h_field_policy_blocks_agent_write() -> None:
    policy = phase_h._phase_h_field_policy({"fields": []})
    field = policy["fields"][0]

    assert field["field_key"] == "Transcripcion_Ultimo_Audio"
    assert field["writable"] is False
    assert field["allowed_sources"] == ["audio.transcribe"]
    assert field["write_policy"] == "system_audio_pipeline_only"
    assert field["write_policy_metadata"]["blocked_for_agent"] is True
    assert field["write_policy_metadata"]["speech_api_real"] is False


def test_long_audio_preview_creates_transcription_and_one_question() -> None:
    scenario = phase_h.phase_h_scenarios()[0]
    workflow = _workflow_for("audio.transcribe")
    preview = phase_h._preview_audio_workflow(workflow.definition, scenario)

    assert preview["transcription"]["text"] == scenario.expected_transcription
    assert preview["transcription"]["low_confidence"] is False
    assert preview["field_updates"]["Transcripcion_Ultimo_Audio"]["write_owner"] == (
        "system_audio_pipeline"
    )
    assert preview["agent_turn_input"]["inbound_text"] == scenario.expected_transcription
    assert preview["agent_turn_input"]["usable_for_agent_claims"] is True
    assert preview["customer_message_requests"][0]["variables"] == {
        "siguiente_pregunta": scenario.expected_next_question
    }
    assert phase_h._assert_scenario_preview(scenario, preview) == []


def test_low_confidence_audio_notifies_and_requires_written_confirmation() -> None:
    scenario = next(
        item
        for item in phase_h.phase_h_scenarios()
        if item.key == "low_confidence_audio_requests_written_confirmation"
    )
    workflow = _workflow_for("audio.transcribe")
    preview = phase_h._preview_audio_workflow(workflow.definition, scenario)

    assert preview["transcription"]["low_confidence"] is True
    assert preview["agent_turn_input"]["usable_for_agent_claims"] is False
    assert preview["notifications"][0]["reason"] == "audio_low_confidence"
    assert preview["customer_message_requests"][0]["send_decision"] == "no_send"
    assert phase_h._assert_scenario_preview(scenario, preview) == []


def test_multi_intention_audio_keeps_single_next_question() -> None:
    scenario = next(
        item
        for item in phase_h.phase_h_scenarios()
        if item.key == "audio_with_many_questions_keeps_one_next_question"
    )
    workflow = _workflow_for("audio.transcribe")
    preview = phase_h._preview_audio_workflow(workflow.definition, scenario)

    question = preview["customer_message_requests"][0]["variables"]["siguiente_pregunta"]
    assert question == "cuanto tiempo tienes trabajando"
    assert phase_h._count_question_prompts(question) == 1
    assert phase_h._assert_scenario_preview(scenario, preview) == []


def test_phase_h_lab_all_scenarios_pass_without_side_effects() -> None:
    workflows = {
        key: _workflow_for(key)
        for key in phase_h.PHASE_H_WORKFLOWS
    }
    lab = phase_h._run_phase_h_dry_lab(workflows, phase_h.phase_h_scenarios())

    assert len(lab) == len(phase_h.phase_h_scenarios())
    assert all(result["status"] == "passed" for result in lab)
    assert all(result["send_decision"] == "no_send" for result in lab)
    assert all(result["outbound_outbox_writes"] == 0 for result in lab)
    assert all(result["workflow_execution_writes"] == 0 for result in lab)
    assert all(result["speech_api_real"] is False for result in lab)
    assert all(result["openai_api_real"] is False for result in lab)


def test_assert_preview_detects_audio_api_and_customer_copy_leaks() -> None:
    scenario = phase_h.phase_h_scenarios()[0]
    bad_preview = {
        "speech_api_calls": 1,
        "credential_lookup": True,
        "customer_visible_output": "hola",
        "outbound_outbox_writes": 1,
        "workflow_execution_writes": 1,
        "transcription": {"text": "bad", "low_confidence": True},
        "field_updates": {},
        "customer_message_requests": [],
        "notifications": [],
        "side_effects": {"external_apis": True},
    }

    failures = phase_h._assert_scenario_preview(scenario, bad_preview)

    assert "speech_api_call_present" in failures
    assert "credential_lookup_present" in failures
    assert "customer_visible_output_present" in failures
    assert "outbox_write_present" in failures
    assert "workflow_execution_write_present" in failures
    assert "transcription_mismatch" in failures
    assert "transcription_field_missing" in failures
    assert "customer_message_request_count_mismatch" in failures
    assert "side_effect_present" in failures


def test_scenario_turn_includes_audio_attachment_payload() -> None:
    scenario = phase_h.phase_h_scenarios()[0]
    turn = phase_h._scenario_turn(scenario)

    assert turn["inbound_text"] == "audio_event:long_audio_transcribed_to_turn_input"
    assert turn["attachments"][0]["type"] == "audio"
    assert turn["attachments"][0]["attachment_id"] == "aud-long"


@pytest.mark.asyncio
async def test_phase_h_dry_run_preview_does_not_query_db() -> None:
    result = await phase_h.seed_dinamo_phase_h_audio(
        object(),  # type: ignore[arg-type]
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.pass_count == len(phase_h.phase_h_scenarios())
    assert result.updated_workflows == list(phase_h.PHASE_H_WORKFLOWS)
    assert result.updated_field_permissions == list(phase_h.PHASE_H_SYSTEM_FIELDS)
    assert result.verified_templates == list(phase_h.PHASE_H_TEMPLATES)
    assert result.decision == phase_h.PHASE_H_DECISION_READY
    assert result.as_dict()["speech_api_real"] is False


def test_script_does_not_import_speech_clients_or_call_outbox_or_workflows() -> None:
    source = Path("atendia/scripts/seed_dinamo_phase_h_audio.py").read_text(
        encoding="utf-8"
    )

    assert "from openai" not in source
    assert "import openai" not in source
    assert "speechclient" not in source.lower()
    assert "whisper" not in source.lower()
    assert "transcriptions.create" not in source
    assert "googleapiclient" not in source
    assert "requests." not in source
    assert "httpx." not in source
    assert "stage_outbound" not in source
    assert "enqueue_message" not in source
    assert "execute_workflow(" not in source


class _Workflow:
    def __init__(self, definition: dict) -> None:
        self.definition = definition


def _workflow_for(key: str) -> _Workflow:
    spec = phase_h.phase_h_workflow_specs()[key]
    return _Workflow(phase_h._phase_h_definition(spec))

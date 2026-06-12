from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from atendia.scripts import seed_dinamo_phase_f_followups as phase_f


def test_phase_f_targets_followup_workflows_templates_and_fields() -> None:
    assert phase_f.PHASE_F_WORKFLOWS == ("followup.schedule", "customer_message.request")
    assert phase_f.PHASE_F_SYSTEM_FIELDS == ("Followups_Enviados", "Proximo_Followup")
    assert phase_f.PHASE_F_TEMPLATES == (
        "dinamo_followup_3h_v1",
        "dinamo_followup_12h_v1",
        "dinamo_followup_72h_v1",
    )


def test_followup_node_config_matches_plan_d4() -> None:
    config = phase_f.followup_node_config()

    assert config["attempt_delays_hours"] == [3, 12, 72]
    assert config["max_attempts"] == 3
    assert config["jitter_minutes"] == [2, 10]
    assert config["quiet_hours"]["start"] == "23:00"
    assert config["quiet_hours"]["end"] == "07:00"
    assert set(config["cancel_on"]) == {
        "message_received",
        "Handoff_Humano",
        "no_califica",
        "cerrado_perdido",
        "cerrado_ganado",
    }
    assert list(config["templates"]) == list(phase_f.PHASE_F_TEMPLATES)


def test_in_window_attempts_respect_3h_12h_72h_and_jitter() -> None:
    scenario = phase_f.phase_f_scenarios()[0]
    preview = phase_f.schedule_followups_preview(
        phase_f.followup_node_config(),
        silence_start=datetime.fromisoformat(scenario.silence_start),
        state=dict(scenario.state),
    )

    attempts = preview["attempts"]
    assert [item["delay_hours"] for item in attempts] == [3, 12, 72]
    assert all(item["status"] == "scheduled" for item in attempts)
    assert all(2 <= item["jitter_minutes"] <= 10 for item in attempts)
    assert all(item["queued_from_quiet_hours"] is False for item in attempts)
    assert [item["template"] for item in attempts] == list(phase_f.PHASE_F_TEMPLATES)
    assert phase_f._assert_scenario_preview(scenario, preview) == []


def test_quiet_hours_attempt_queues_until_seven_am() -> None:
    scenario = next(
        item
        for item in phase_f.phase_f_scenarios()
        if item.key == "quiet_hours_queue_first_attempt"
    )
    preview = phase_f.schedule_followups_preview(
        phase_f.followup_node_config(),
        silence_start=datetime.fromisoformat(scenario.silence_start),
        state=dict(scenario.state),
    )

    first = preview["attempts"][0]
    assert first["queued_from_quiet_hours"] is True
    scheduled = datetime.fromisoformat(first["scheduled_for"])
    assert scheduled.hour == 7
    assert first["status"] == "scheduled"
    assert phase_f._assert_scenario_preview(scenario, preview) == []


def test_reply_cancels_remaining_attempts() -> None:
    scenario = next(
        item for item in phase_f.phase_f_scenarios() if item.key == "reply_cancels_remaining"
    )
    preview = phase_f.schedule_followups_preview(
        phase_f.followup_node_config(),
        silence_start=datetime.fromisoformat(scenario.silence_start),
        state=dict(scenario.state),
        cancel_events=scenario.cancel_events,
    )

    statuses = [item["status"] for item in preview["attempts"]]
    assert statuses == ["scheduled", "cancelled", "cancelled"]
    assert preview["cancel_reason"] == "message_received"
    assert phase_f._assert_scenario_preview(scenario, preview) == []


def test_handoff_and_terminal_stage_cancel_followups() -> None:
    by_key = {item.key: item for item in phase_f.phase_f_scenarios()}
    config = phase_f.followup_node_config()

    handoff = by_key["handoff_cancels_all"]
    preview = phase_f.schedule_followups_preview(
        config,
        silence_start=datetime.fromisoformat(handoff.silence_start),
        state=dict(handoff.state),
        cancel_events=handoff.cancel_events,
    )
    assert all(item["status"] == "cancelled" for item in preview["attempts"])
    assert preview["cancel_reason"] == "Handoff_Humano"

    terminal = by_key["terminal_stage_cancels_pending"]
    preview = phase_f.schedule_followups_preview(
        config,
        silence_start=datetime.fromisoformat(terminal.silence_start),
        state=dict(terminal.state),
        cancel_events=terminal.cancel_events,
    )
    assert [item["status"] for item in preview["attempts"]] == [
        "scheduled",
        "scheduled",
        "cancelled",
    ]
    assert preview["cancel_reason"] == "cerrado_perdido"


def test_missing_template_variable_fails_closed_without_improvising() -> None:
    scenario = next(
        item
        for item in phase_f.phase_f_scenarios()
        if item.key == "missing_variable_fails_closed"
    )
    preview = phase_f.schedule_followups_preview(
        phase_f.followup_node_config(),
        silence_start=datetime.fromisoformat(scenario.silence_start),
        state=dict(scenario.state),
    )

    second = preview["attempts"][1]
    assert second["status"] == "blocked_missing_variable"
    assert set(second["missing_variables"]) == {"Moto", "Plan_Credito_Sentence"}
    assert phase_f._assert_scenario_preview(scenario, preview) == []


def test_max_attempts_never_exceeds_three() -> None:
    config = phase_f.followup_node_config()
    for scenario in phase_f.phase_f_scenarios():
        preview = phase_f.schedule_followups_preview(
            config,
            silence_start=datetime.fromisoformat(scenario.silence_start),
            state=dict(scenario.state),
            cancel_events=scenario.cancel_events,
        )
        assert len(preview["attempts"]) == 3
        assert preview["max_attempts"] == 3


def test_phase_f_lab_all_scenarios_pass_without_side_effects() -> None:
    lab = phase_f._run_phase_f_dry_lab(phase_f.phase_f_scenarios())

    assert len(lab) == len(phase_f.phase_f_scenarios())
    assert all(result["status"] == "passed" for result in lab)
    assert all(result["send_decision"] == "no_send" for result in lab)
    assert all(result["outbound_outbox_writes"] == 0 for result in lab)
    assert all(result["workflow_execution_writes"] == 0 for result in lab)
    assert all(result["openai_api_real"] is False for result in lab)


def test_assert_preview_detects_quiet_hours_violation_and_bad_jitter() -> None:
    scenario = phase_f.phase_f_scenarios()[0]
    bad_preview = {
        "attempts": [
            {
                "status": "scheduled",
                "queued_from_quiet_hours": False,
                "template": "dinamo_followup_3h_v1",
                "send_decision": "no_send",
                "jitter_minutes": 30,
                "scheduled_for": "2026-06-16T03:00",
                "missing_variables": [],
            },
            {
                "status": "scheduled",
                "queued_from_quiet_hours": False,
                "template": "dinamo_followup_12h_v1",
                "send_decision": "no_send",
                "jitter_minutes": 5,
                "scheduled_for": "2026-06-15T21:06",
                "missing_variables": [],
            },
            {
                "status": "scheduled",
                "queued_from_quiet_hours": False,
                "template": "dinamo_followup_72h_v1",
                "send_decision": "no_send",
                "jitter_minutes": 5,
                "scheduled_for": "2026-06-18T09:10",
                "missing_variables": [],
            },
        ],
        "cancel_reason": None,
        "outbound_outbox_writes": 0,
        "workflow_execution_writes": 0,
    }

    failures = phase_f._assert_scenario_preview(scenario, bad_preview)

    assert "jitter_out_of_range:attempt_1" in failures
    assert "scheduled_inside_quiet_hours:attempt_1" in failures


@pytest.mark.asyncio
async def test_phase_f_dry_run_preview_does_not_query_db() -> None:
    result = await phase_f.seed_dinamo_phase_f_followups(
        object(),  # type: ignore[arg-type]
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.pass_count == len(phase_f.phase_f_scenarios())
    assert result.updated_workflows == list(phase_f.PHASE_F_WORKFLOWS)
    assert result.updated_field_permissions == list(phase_f.PHASE_F_SYSTEM_FIELDS)
    assert result.verified_templates == list(phase_f.PHASE_F_TEMPLATES)
    assert result.decision == phase_f.PHASE_F_DECISION_READY


def test_script_does_not_enqueue_send_or_execute_workflows() -> None:
    source = Path("atendia/scripts/seed_dinamo_phase_f_followups.py").read_text(
        encoding="utf-8"
    )

    assert "from openai" not in source
    assert "import openai" not in source
    assert "stage_outbound" not in source
    assert "enqueue_message" not in source
    assert "execute_workflow(" not in source
    assert "SendAdapter" not in source

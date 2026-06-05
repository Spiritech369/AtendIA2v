from __future__ import annotations

from atendia.workflows.engine import TRIGGERS, _trigger_matches


def test_agent_runtime_events_are_registered_as_workflow_triggers():
    assert "agent_turn_completed" in TRIGGERS
    assert "agent_confidence_low" in TRIGGERS
    assert "agent_policy_blocked" in TRIGGERS


def test_agent_runtime_trigger_conditions_match_supported_payload_fields():
    payload = {
        "confidence": 0.42,
        "action_id": "add_tag",
        "field_key": "budget",
        "lifecycle_stage": "qualified",
        "risk_flags": ["knowledge_gap"],
    }

    assert _trigger_matches(
        {
            "confidence_lte": 0.5,
            "action_ids": ["add_tag"],
            "field_keys": ["budget"],
            "lifecycle_stages": ["qualified"],
            "risk_flags": ["knowledge_gap"],
        },
        payload,
    )
    assert not _trigger_matches({"confidence_lt": 0.4}, payload)
    assert not _trigger_matches({"action_id": "close_conversation"}, payload)
    assert not _trigger_matches({"field_key": "email"}, payload)
    assert not _trigger_matches({"lifecycle_stage": "lost"}, payload)
    assert not _trigger_matches({"risk_flags": ["sensitive_data"]}, payload)

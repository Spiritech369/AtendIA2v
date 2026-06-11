from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.product_agents.smoke_policy import (
    EXACT_APPROVAL_TEXT,
    evaluate_smoke_send,
    legacy_send_suppressed_for_smoke,
    phone_in_smoke_allowlist,
)

PHONE = "+5218128889241"


def _smoke_metadata(**overrides):
    metadata = {
        "respond_style_live_send_enabled": True,
        "respond_style_send_scope": "approved_contact_only",
        "respond_style_live_allowed_phones": ["8128889241"],
        "respond_style_workflows_enabled": False,
        "respond_style_actions_enabled": False,
        "respond_style_legacy_fallback_enabled": False,
        "respond_style_fail_closed_notify_operator": True,
        "respond_style_smoke_approval_text": EXACT_APPROVAL_TEXT,
        "respond_style_preflight_passed_at": "2026-06-10T00:00:00Z",
    }
    metadata.update(overrides)
    return metadata


def _valid_result(**overrides):
    base = {
        "validation_result": {"status": "valid"},
        "blocked_reason": None,
        "final_message": "Hola, te ayudo con gusto.",
        "workflow_event_proposals": [],
        "action_proposals": [],
        "side_effects": {"delivery": False, "workflows": False, "actions": False},
        "handoff_proposal": None,
        "trace": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _canonical_deployment(**overrides):
    columns = {
        "send_enabled": True,
        "outbox_enabled": True,
        "live_send_enabled": True,
        "single_contact_smoke_enabled": True,
        "send_scope": "approved_contact_only",
    }
    columns.update(overrides)
    return SimpleNamespace(**columns)


def _eval(metadata=None, result=None, phone=PHONE, takeover=False, deployment=...):
    return evaluate_smoke_send(
        metadata=metadata if metadata is not None else _smoke_metadata(),
        from_phone=phone,
        result=result if result is not None else _valid_result(),
        takeover_pending=takeover,
        deployment=_canonical_deployment() if deployment is ... else deployment,
    )


def test_allowed_phone_valid_turn_is_sendable() -> None:
    evaluation = _eval()
    assert evaluation.active and evaluation.allowed
    assert evaluation.phone_normalized == "8128889241"


def test_non_allowed_phone_stays_shadow() -> None:
    evaluation = _eval(phone="+5218111111111")
    assert evaluation.active and not evaluation.allowed
    assert "phone_not_allowlisted" in evaluation.reasons


def test_flags_off_is_pure_noop() -> None:
    evaluation = _eval(metadata={})
    assert not evaluation.active and not evaluation.allowed


def test_validator_fail_blocks_send() -> None:
    evaluation = _eval(result=_valid_result(validation_result={"status": "blocked"}))
    assert not evaluation.allowed
    assert "validator_not_passed" in evaluation.reasons


def test_missing_final_message_blocks_send() -> None:
    evaluation = _eval(result=_valid_result(final_message=""))
    assert not evaluation.allowed
    assert "final_message_missing" in evaluation.reasons


def test_blocked_turn_blocks_send() -> None:
    evaluation = _eval(
        result=_valid_result(blocked_reason="required_tool_failed", final_message=None)
    )
    assert not evaluation.allowed
    assert "turn_blocked" in evaluation.reasons


def test_workflow_or_action_proposals_block_send() -> None:
    with_workflows = _eval(
        result=_valid_result(workflow_event_proposals=[{"binding_name": "x"}])
    )
    assert "workflow_proposals_present" in with_workflows.reasons
    with_actions = _eval(result=_valid_result(action_proposals=[{"name": "x"}]))
    assert "action_proposals_present" in with_actions.reasons
    flag_on = _eval(metadata=_smoke_metadata(respond_style_workflows_enabled=True))
    assert "workflows_must_be_disabled" in flag_on.reasons


def test_handoff_accepted_allows_ack_and_requires_pause() -> None:
    evaluation = _eval(
        result=_valid_result(handoff_proposal={"target": "ventas", "needed": True})
    )
    assert evaluation.allowed
    assert evaluation.pause_after_send is True


def test_takeover_pending_blocks_send() -> None:
    evaluation = _eval(takeover=True)
    assert not evaluation.allowed
    assert "human_takeover_pending" in evaluation.reasons


def test_rollback_flag_disables_send() -> None:
    evaluation = _eval(metadata=_smoke_metadata(respond_style_rollback_active=True))
    assert not evaluation.allowed
    assert "rollback_active" in evaluation.reasons
    fully_off = _eval(metadata=_smoke_metadata(respond_style_live_send_enabled=False))
    assert not fully_off.active


def test_unsafe_scopes_never_send() -> None:
    for scope in ("all_contacts", "all", "tenant", "canary", "production"):
        evaluation = _eval(metadata=_smoke_metadata(respond_style_send_scope=scope))
        assert not evaluation.allowed
        assert "send_scope_unsafe" in evaluation.reasons


def test_approval_and_preflight_required() -> None:
    short_approval = _eval(
        metadata=_smoke_metadata(respond_style_smoke_approval_text="apruebo")
    )
    assert "approval_text_missing_or_inexact" in short_approval.reasons
    no_preflight = _eval(
        metadata=_smoke_metadata(respond_style_preflight_passed_at=None)
    )
    assert "preflight_not_passed" in no_preflight.reasons


def test_legacy_suppression_scope() -> None:
    metadata = _smoke_metadata()
    assert legacy_send_suppressed_for_smoke(metadata, PHONE) is True
    assert legacy_send_suppressed_for_smoke(metadata, "+5218111111111") is False
    assert legacy_send_suppressed_for_smoke({}, PHONE) is False
    off = _smoke_metadata(respond_style_live_send_enabled=False)
    assert legacy_send_suppressed_for_smoke(off, PHONE) is False


def test_phone_allowlist_normalizes_variants() -> None:
    metadata = _smoke_metadata()
    assert phone_in_smoke_allowlist(metadata, "+52 1 812 888 9241") is True
    assert phone_in_smoke_allowlist(metadata, "8128889241") is True
    assert phone_in_smoke_allowlist(metadata, "8128889242") is False


@pytest.mark.asyncio
async def test_stage_smoke_send_metadata(monkeypatch) -> None:
    from atendia.product_agents import smoke_policy

    captured = {}

    async def fake_stage_outbound(session, msg):
        captured["msg"] = msg
        return uuid4()

    import atendia.queue.outbox as outbox_module

    monkeypatch.setattr(outbox_module, "stage_outbound", fake_stage_outbound)

    info = await smoke_policy.stage_smoke_send(
        object(),
        tenant_id=str(uuid4()),
        deployment_id="dep-1",
        agent_version_id="ver-1",
        conversation_id="conv-1",
        inbound_message_id="msg-1",
        to_phone_e164=PHONE,
        final_message="Hola",
        model="gpt-4o",
        trace_id="trace-1",
        send_scope="approved_contact_only",
        validator_status="valid",
    )
    assert info["staged"] is True
    assert info["source"] == "respond_style_single_contact_smoke"
    assert info["idempotency_key"] == "rs-smoke-msg-1"
    metadata = captured["msg"].metadata
    assert metadata["smoke_session_id"] == info["smoke_session_id"]
    assert metadata["trace_id"] == "trace-1"
    assert metadata["send_scope"] == "approved_contact_only"
    assert metadata["phone_normalized"] == "8128889241"


def test_canonical_columns_required_even_with_metadata_on() -> None:
    """Metadata alone must never arm visible sends: the deployment's
    canonical boolean columns are required too."""
    for column in (
        "send_enabled",
        "outbox_enabled",
        "live_send_enabled",
        "single_contact_smoke_enabled",
    ):
        evaluation = _eval(deployment=_canonical_deployment(**{column: False}))
        assert not evaluation.allowed
        assert "canonical_send_columns_disabled" in evaluation.reasons
    missing_deployment = _eval(deployment=None)
    assert not missing_deployment.allowed
    assert "canonical_send_columns_disabled" in missing_deployment.reasons
    assert "canonical_send_scope_unsafe" in missing_deployment.reasons


def test_metadata_cannot_send_when_canonical_flags_are_no_send() -> None:
    """Regression for the real smoke incident: metadata re-arm cannot stage
    visible sends when the deployment columns still say no-send/none."""
    deployment = _canonical_deployment(
        send_enabled=False,
        outbox_enabled=False,
        live_send_enabled=False,
        single_contact_smoke_enabled=False,
        send_scope="none",
    )
    evaluation = _eval(metadata=_smoke_metadata(), deployment=deployment)
    assert evaluation.active is True
    assert evaluation.allowed is False
    assert "canonical_send_columns_disabled" in evaluation.reasons
    assert "canonical_send_scope_unsafe" in evaluation.reasons


def test_canonical_send_scope_required_even_with_metadata_scope_on() -> None:
    evaluation = _eval(deployment=_canonical_deployment(send_scope="none"))
    assert evaluation.active is True
    assert evaluation.allowed is False
    assert "canonical_send_scope_unsafe" in evaluation.reasons


def test_live_grounding_blocks_dry_facts_for_visible_send() -> None:
    """Dry/test facts can never ground a customer-visible turn."""
    from atendia.agent_runtime import (
        AgentContextPackage,
        LLMAgentTurnOutput,
        RespondStyleTurnValidator,
    )

    context = AgentContextPackage(
        send_policy={"visible_send_candidate": True},
        tool_results=[
            {
                "tool_name": "catalog.search",
                "status": "succeeded",
                "source_kind": "dry_facts",
            }
        ],
    )
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Tenemos varios modelos disponibles.",
            confidence=0.8,
        ),
        context=context,
    )
    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    codes = {item.code for item in decision.validation.blocked_items}
    assert "live_claim_source_not_real" in codes

    # Same turn with REAL grounding passes.
    real_context = AgentContextPackage(
        send_policy={"visible_send_candidate": True},
        tool_results=[
            {
                "tool_name": "catalog.search",
                "status": "succeeded",
                "source_kind": "real_catalog",
            }
        ],
    )
    ok = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Tenemos varios modelos disponibles.",
            confidence=0.8,
        ),
        context=real_context,
    )
    assert ok.send_decision == "send"

    # Shadow turns (not visible-send candidates) keep using dry facts.
    shadow_context = AgentContextPackage(
        tool_results=[
            {
                "tool_name": "catalog.search",
                "status": "succeeded",
                "source_kind": "dry_facts",
            }
        ],
    )
    shadow = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Tenemos varios modelos disponibles.",
            confidence=0.8,
        ),
        context=shadow_context,
    )
    assert shadow.send_decision == "send"

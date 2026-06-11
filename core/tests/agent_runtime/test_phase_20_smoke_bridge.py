from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.agent_runtime import (
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMHandoffProposal,
    RespondStyleToolLoop,
)
from atendia.product_agents.smoke_policy import EXACT_APPROVAL_TEXT

PHONE = "+5218128889241"


def _smoke_metadata(**overrides):
    metadata = {
        "respond_style_enabled": True,
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


def _valid_decision(message, handoff=None):
    return FinalTurnDecision(
        final_message=message,
        send_decision="no_send",
        validation=AgentTurnValidationResult(status="valid", send_decision="no_send"),
        accepted_handoff=handoff,
    )


def _bridge_fixtures(monkeypatch, *, metadata, decisions, takeover=False):
    from atendia.product_agents import agent_service_bridge as bridge
    from atendia.product_agents import smoke_policy

    tenant_id = uuid4()
    deployment = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=uuid4(),
        active_version_id=uuid4(),
        metadata_json=metadata,
    )
    version = SimpleNamespace(
        id=deployment.active_version_id,
        tenant_id=tenant_id,
        agent_id=deployment.agent_id,
        status="published_no_send",
        role="generic advisor",
        tone="brief",
        language="es",
        instructions="help",
        knowledge_policy={},
        tool_policy={"bindings": []},
        action_policy={},
        workflow_policy={},
        field_policy={"fields": []},
        safety_policy={"handoff": {"enabled": True, "targets": ["team"]}},
    )

    async def fake_resolve(session, *, tenant_id, channel=None):
        return deployment, False

    async def fake_blockers(session, **kwargs):
        return []

    async def fake_transcript(session, *, conversation_id):
        return []

    async def fake_load_shadow(session, *, conversation_id):
        return {}, {}

    async def fake_save_shadow(session, **kwargs):
        return None

    async def fake_handoff_pending(session, *, conversation_id):
        return False

    async def fake_takeover(session, *, conversation_id):
        return takeover

    class _ScriptedProvider:
        def __init__(self, items):
            self._items = list(items)

        async def generate(self, *, turn_input, context):
            return self._items.pop(0)

    class _NoTools:
        def execute_tool(self, tool_call, context):  # pragma: no cover
            raise AssertionError("no tools")

    monkeypatch.setattr(bridge, "_resolve_opted_in_deployment", fake_resolve)
    monkeypatch.setattr(bridge, "respond_style_publish_blockers", fake_blockers)
    monkeypatch.setattr(bridge, "_recent_transcript", fake_transcript)
    monkeypatch.setattr(bridge, "_load_shadow_state", fake_load_shadow)
    monkeypatch.setattr(bridge, "_save_shadow_fields", fake_save_shadow)
    monkeypatch.setattr(bridge, "_recent_handoff_pending", fake_handoff_pending)
    monkeypatch.setattr(
        bridge, "get_settings", lambda: SimpleNamespace(openai_api_key="k")
    )
    monkeypatch.setattr(
        bridge,
        "build_tool_loop",
        lambda config, api_key, model=None: RespondStyleToolLoop(
            provider=_ScriptedProvider(decisions), executor=_NoTools()
        ),
    )
    monkeypatch.setattr(smoke_policy, "get_takeover_pending", fake_takeover)

    staged_calls = []

    async def fake_stage(session, **kwargs):
        staged_calls.append(kwargs)
        return {
            "staged": True,
            "outbox_id": str(uuid4()),
            "smoke_session_id": str(uuid4()),
            "idempotency_key": "k",
            "source": "respond_style_single_contact_smoke",
        }

    monkeypatch.setattr(smoke_policy, "stage_smoke_send", fake_stage)

    notified = []

    async def fake_notify(session, **kwargs):
        notified.append(kwargs)
        return str(uuid4())

    monkeypatch.setattr(smoke_policy, "notify_operator_fail_closed", fake_notify)

    paused = []

    async def fake_set_takeover(session, **kwargs):
        paused.append(kwargs)

    monkeypatch.setattr(smoke_policy, "set_takeover_pending", fake_set_takeover)

    class _Session:
        async def get(self, model, key):
            return version

    return SimpleNamespace(
        bridge=bridge,
        session=_Session(),
        tenant_id=tenant_id,
        staged=staged_calls,
        notified=notified,
        paused=paused,
    )


@pytest.mark.asyncio
async def test_bridge_stages_send_for_allowed_phone(monkeypatch) -> None:
    fx = _bridge_fixtures(
        monkeypatch,
        metadata=_smoke_metadata(),
        decisions=[_valid_decision("Hola, te ayudo.")],
    )
    outcome = await fx.bridge.maybe_handle_respond_style_turn(
        fx.session,
        tenant_id=str(fx.tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        mode="no_send",
        from_phone_e164=PHONE,
        inbound_message_id=str(uuid4()),
    )
    assert outcome.smoke["active"] is True
    assert outcome.smoke["allowed"] is True
    assert outcome.smoke["staged"] is True
    assert len(fx.staged) == 1
    assert fx.staged[0]["to_phone_e164"] == PHONE


@pytest.mark.asyncio
async def test_bridge_does_not_stage_for_non_allowed_phone(monkeypatch) -> None:
    fx = _bridge_fixtures(
        monkeypatch,
        metadata=_smoke_metadata(),
        decisions=[_valid_decision("Hola.")],
    )
    outcome = await fx.bridge.maybe_handle_respond_style_turn(
        fx.session,
        tenant_id=str(fx.tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        mode="no_send",
        from_phone_e164="+5218111111111",
        inbound_message_id=str(uuid4()),
    )
    # Shadow continues exactly as before: candidate exists, nothing staged,
    # nobody paged (this contact is not the smoke target).
    assert outcome.result.final_message == "Hola."
    assert outcome.smoke["staged"] is False
    assert "phone_not_allowlisted" in outcome.smoke["reasons"]
    assert fx.staged == []
    assert fx.notified == []


@pytest.mark.asyncio
async def test_bridge_flags_off_never_touches_smoke(monkeypatch) -> None:
    fx = _bridge_fixtures(
        monkeypatch,
        metadata={"respond_style_enabled": True},
        decisions=[_valid_decision("Hola.")],
    )
    outcome = await fx.bridge.maybe_handle_respond_style_turn(
        fx.session,
        tenant_id=str(fx.tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="hola",
        mode="no_send",
        from_phone_e164=PHONE,
    )
    assert outcome.smoke["active"] is False
    assert outcome.smoke["staged"] is False
    assert fx.staged == []


@pytest.mark.asyncio
async def test_bridge_takeover_short_circuits_before_llm(monkeypatch) -> None:
    fx = _bridge_fixtures(
        monkeypatch, metadata=_smoke_metadata(), decisions=[], takeover=True
    )
    outcome = await fx.bridge.maybe_handle_respond_style_turn(
        fx.session,
        tenant_id=str(fx.tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="sigues ahi?",
        mode="no_send",
        from_phone_e164=PHONE,
    )
    # No LLM call (empty decisions never popped), no send, quiet followup
    # that does not page the operator on every message.
    assert outcome.blocked_reason == "human_takeover_pending"
    assert outcome.smoke["takeover_pending"] is True
    assert outcome.no_send_followup["action"] == "human_takeover_pending"
    assert outcome.no_send_followup["notify_operator"] is False
    assert fx.staged == []


@pytest.mark.asyncio
async def test_bridge_handoff_send_sets_takeover(monkeypatch) -> None:
    handoff = LLMHandoffProposal(
        needed=True, reason="customer asked", target="team", priority="normal"
    )
    fx = _bridge_fixtures(
        monkeypatch,
        metadata=_smoke_metadata(),
        decisions=[_valid_decision("Te conecto con el equipo.", handoff=handoff)],
    )
    outcome = await fx.bridge.maybe_handle_respond_style_turn(
        fx.session,
        tenant_id=str(fx.tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="pasame con alguien",
        mode="no_send",
        from_phone_e164=PHONE,
        inbound_message_id=str(uuid4()),
    )
    assert outcome.smoke["staged"] is True
    assert outcome.smoke.get("takeover_pending_set") is True
    assert len(fx.paused) == 1


@pytest.mark.asyncio
async def test_bridge_fail_closed_notifies_operator_no_fallback(monkeypatch) -> None:
    blocked = FinalTurnDecision(
        final_message=None,
        send_decision="no_send",
        validation=AgentTurnValidationResult(
            status="blocked",
            send_decision="no_send",
            blocked_reason="hard_policy_unsupported",
            blocked_items=[],
        ),
    )
    fx = _bridge_fixtures(
        monkeypatch, metadata=_smoke_metadata(), decisions=[blocked, blocked]
    )
    outcome = await fx.bridge.maybe_handle_respond_style_turn(
        fx.session,
        tenant_id=str(fx.tenant_id),
        conversation_id=str(uuid4()),
        inbound_text="cuanto cuesta",
        mode="no_send",
        from_phone_e164=PHONE,
        inbound_message_id=str(uuid4()),
    )
    # No send, no fallback copy of any kind, operator paged with the reason.
    assert outcome.smoke["staged"] is False
    assert outcome.smoke.get("operator_notified") is True
    assert fx.staged == []
    assert len(fx.notified) == 1
    assert outcome.result.final_message is None


def test_legacy_suppression_helper_in_send_adapter() -> None:
    # The legacy choke point exists and is scoped: source-level guarantees.
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "atendia"
        / "agent_runtime"
        / "send_adapter.py"
    ).read_text(encoding="utf-8")
    assert "legacy_suppressed_for_smoke" in source
    assert "approved_contact_only" in source
    # Fails open: suppression must never break other contacts.
    assert "return False" in source

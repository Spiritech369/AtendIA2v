from __future__ import annotations

from datetime import date
from uuid import uuid4

from atendia.agent_runtime.model_provider import build_minimized_turn_payload
from atendia.agent_runtime.provider_quality_gate import (
    expected_approval_record_path,
    local_deterministic_readiness_final,
    provider_external_allowed,
    write_pending_approval_record,
)
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    CustomerContext,
    KnowledgeCitation,
    MessageContext,
    TurnContext,
)
from atendia.config import Settings


def _settings(**overrides):
    values = {
        "_env_file": None,
        "agent_runtime_v2_enabled": True,
        "agent_runtime_v2_send_enabled": False,
        "agent_runtime_v2_actions_enabled": False,
        "agent_runtime_v2_workflow_events_enabled": False,
        "agent_runtime_v2_model_provider": "openai",
        "openai_api_key": "sk-test",
    }
    values.update(overrides)
    return Settings(**values)


def test_provider_externo_bloqueado_sin_approval(tmp_path):
    tenant_id = uuid4()
    agent_id = uuid4()

    record = provider_external_allowed(
        tenant_id=tenant_id,
        agent_id=agent_id,
        provider="openai",
        settings=_settings(),
        report_date=date(2026, 6, 1),
        reports_dir=tmp_path,
    )

    assert record.approved is False
    assert "approval record not found" in record.reasons


def test_provider_externo_permitido_con_approval_y_flags_correctos(tmp_path):
    tenant_id = uuid4()
    agent_id = uuid4()
    path = expected_approval_record_path(report_date=date(2026, 6, 1), reports_dir=tmp_path)
    path.write_text(
        f"""# Provider approval

- approval_status: `approved`
- approver: `Security Owner`
- tenant_id: `{tenant_id}`
- agent_id: `{agent_id}`
- provider: `openai`
- model: `gpt-4o-mini`
- retention mode: `zero_retention`
- region/data policy: `approved_region`
- allowed data categories: `tenant_prompt`, `knowledge_snippets`, `conversation_context`
- forbidden data categories: `attachments`, `tokens`, `secrets`
- scope: `test-turn/preview/simulation/shadow only`
- send_enabled: `false`
- actions_enabled: `false`
- workflow_events_enabled: `false`
""",
        encoding="utf-8",
    )

    record = provider_external_allowed(
        tenant_id=tenant_id,
        agent_id=agent_id,
        provider="openai",
        settings=_settings(),
        report_date=date(2026, 6, 1),
        reports_dir=tmp_path,
    )

    assert record.approved is True
    assert record.reasons == []


def test_provider_externo_bloqueado_si_flags_peligrosos_estan_activos(tmp_path):
    tenant_id = uuid4()
    agent_id = uuid4()
    path = expected_approval_record_path(report_date=date(2026, 6, 1), reports_dir=tmp_path)
    path.write_text(
        f"""# Provider approval

- approval_status: `approved`
- approver: `Security Owner`
- tenant_id: `{tenant_id}`
- agent_id: `{agent_id}`
- provider: `openai`
- model: `gpt-4o-mini`
- retention mode: `zero_retention`
- region/data policy: `approved_region`
- allowed data categories: `tenant_prompt`, `knowledge_snippets`, `conversation_context`
- forbidden data categories: `attachments`, `tokens`, `secrets`
- scope: `test-turn/preview/simulation/shadow only`
- send_enabled: `false`
- actions_enabled: `false`
- workflow_events_enabled: `false`
""",
        encoding="utf-8",
    )

    record = provider_external_allowed(
        tenant_id=tenant_id,
        agent_id=agent_id,
        provider="openai",
        settings=_settings(agent_runtime_v2_send_enabled=True),
        report_date=date(2026, 6, 1),
        reports_dir=tmp_path,
    )

    assert record.approved is False
    assert "global send flag is enabled" in record.reasons


def test_payload_minimization_excluye_pii_y_secrets():
    context = TurnContext(
        tenant_id="tenant",
        conversation_id="conversation",
        inbound_text="Mi tel es 8112345678 y correo ana@example.com",
        customer=CustomerContext(
            phone_e164="+528112345678",
            email="ana@example.com",
            attrs={"secret": "do-not-send"},
        ),
        messages=[
            MessageContext(role="customer", text=f"msg {idx} 8112345678")
            for idx in range(9)
        ],
        active_agent=ActiveAgentContext(
            id="agent",
            instructions="safe",
            metadata={"secret_config": "hidden"},
        ),
        knowledge_citations=[
            KnowledgeCitation(
                source_id=f"source-{idx}",
                title="KB",
                snippet="ana@example.com 8112345678 " + ("x" * 900),
                metadata={"content_type": "faq", "secret": "hidden"},
            )
            for idx in range(7)
        ],
    )

    payload = build_minimized_turn_payload(context)
    serialized = str(payload)

    assert "ana@example.com" not in serialized
    assert "8112345678" not in serialized
    assert "+528112345678" not in serialized
    assert "do-not-send" not in serialized
    assert "secret_config" not in serialized
    assert "hidden" not in serialized
    assert len(payload["conversation_history"]) == 6
    assert len(payload["knowledge_citations"]) == 5
    assert payload["payload_minimization"]["contact_field_values_included"] is False
    assert payload["payload_minimization"]["attachments_included"] is False


def test_local_deterministic_nunca_marca_readiness_final():
    assert local_deterministic_readiness_final() is False


def test_pending_approval_record_crea_template_bloqueado(tmp_path):
    tenant_id = uuid4()
    agent_id = uuid4()

    path = write_pending_approval_record(
        tenant_id=tenant_id,
        agent_id=agent_id,
        report_date=date(2026, 6, 1),
        reports_dir=tmp_path,
    )

    text = path.read_text(encoding="utf-8")
    assert "approval_status: `not_approved`" in text
    assert str(tenant_id) in text
    assert str(agent_id) in text

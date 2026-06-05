from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from atendia.contracts.message import Message, MessageDirection
from atendia.channels.base import OutboundMessage
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.models.outbound_outbox import OutboundOutbox
from atendia.db.models.tenant import Tenant
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.session import _get_factory
from atendia.runner.advisor_brain import AdvisorBrain, advisor_brain_canary_allowed, advisor_brain_feature_config
from atendia.runner.advisor_brain_protocol import (
    AgentBrainCommercialGoal,
    AgentBrainPlan,
    AgentBrainPlanUnderstanding,
    AgentBrainToolPlanStep,
    AdvisorBrainInput,
    AdvisorBrainMode,
    AdvisorBrainOutput,
    AdvisorBrainResult,
    AdvisorBrainStateWritePlan,
    AdvisorBrainToolRequest,
)
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
from atendia.runner.conversation_runner import (
    ConversationRunner,
    _apply_advisor_brain_primary_response,
)
from atendia.runner.nlu_protocol import UsageMetadata
from atendia.runner.sales_advisor_decision_policy import SalesAdvisorDecision

REPO_ROOT = Path(__file__).resolve().parents[3]
MANUAL_WHATSAPP_TEST_PATH = REPO_ROOT / "scripts" / "run_dinamo_advisor_brain_manual_whatsapp_test.py"


def _load_manual_whatsapp_test_module():
    if not MANUAL_WHATSAPP_TEST_PATH.exists():
        pytest.skip(
            "legacy manual WhatsApp advisor-brain harness is missing; "
            "quarantined until restored or migrated to Eval Lab.",
        )
    spec = importlib.util.spec_from_file_location("manual_whatsapp_test_harness", MANUAL_WHATSAPP_TEST_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _StubNLU:
    async def classify(self, **_: object) -> tuple[NLUResult, UsageMetadata | None]:
        return (
            NLUResult(
                intent=Intent.ASK_INFO,
                topic="credito",
                sub_intent="info",
                sales_signal="medium",
                entities={},
                sentiment=Sentiment.NEUTRAL,
                confidence=0.9,
            ),
            UsageMetadata(
                model="stub-nlu",
                tokens_in=1,
                tokens_out=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _StubComposer:
    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        del input
        return (
            ComposerOutput(
                messages=["Claro, te ayudo. Dime que modelo te interesa."],
                raw_llm_response='{"messages":["Claro, te ayudo. Dime que modelo te interesa."]}',
            ),
            UsageMetadata(
                model="scripted-composer",
                tokens_in=1,
                tokens_out=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _FixedBrain:
    def __init__(self, result: AdvisorBrainResult) -> None:
        self._result = result

    async def run(self, *, input, mode, final_response_source):
        del input, mode, final_response_source
        return self._result


def _brain_plan(
    *,
    proposed_final_action: str = "search_catalog",
    proposed_final_action_payload: dict | None = None,
    proposed_state_updates: dict | None = None,
    tool_plan: list[dict] | None = None,
) -> AgentBrainPlan:
    return AgentBrainPlan(
        understanding=AgentBrainPlanUnderstanding(
            customer_message_summary="Cliente requiere seguimiento comercial.",
            detected_intents=["resolve_model"],
            entities={"CREDITO": "Pensionados"},
            context_resolution={"pending_field": None},
            confidence=0.9,
        ),
        commercial_goal=AgentBrainCommercialGoal(
            current_goal="resolve_model",
            next_required_step="resolve_model",
            reason="Contrato de prueba.",
        ),
        tool_plan=[
            AgentBrainToolPlanStep.model_validate(item)
            for item in (tool_plan or [])
        ],
        proposed_state_updates=proposed_state_updates or {},
        proposed_pipeline_update=None,
        proposed_final_action=proposed_final_action,
        proposed_final_action_payload=proposed_final_action_payload or {
            "status": "ok",
            "request_type": "resolve_model",
            "query": "Adventure",
        },
        customer_response_goal="Responder en tono humano y avanzar el flujo.",
        safety_notes=["no_prometer_aprobacion"],
        needs_human_handoff=False,
    )


def _brain_output(
    *,
    next_human_step: str = "resolve_model",
    natural_response: str = "Ya tengo tu perfil. Ahora dime que modelo te interesa.",
    detected_intent: str = "resolve_model",
    new_facts_to_write: dict | None = None,
    corrected_facts: dict | None = None,
    handoff_required: bool = False,
    plan: AgentBrainPlan | None = None,
) -> AdvisorBrainOutput:
    return AdvisorBrainOutput.model_validate(
        {
            "customer_understanding": "Cliente requiere seguimiento comercial.",
            "conversation_memory_used": ["CREDITO=Pensionados"],
            "detected_intent": detected_intent,
            "known_facts": {"CREDITO": "Pensionados"},
            "new_facts_to_write": new_facts_to_write or {},
            "corrected_facts": corrected_facts or {},
            "missing_required_facts": [],
            "next_human_step": next_human_step,
            "tool_requests": [],
            "forbidden_actions": ["no_prometer_aprobacion"],
            "natural_response": natural_response,
            "confidence": 0.9,
            "handoff_required": handoff_required,
            "handoff_reason": "sensitive_payment_or_human_request" if handoff_required else None,
            "state_write_plan": AdvisorBrainStateWritePlan(
                new_facts_to_write=new_facts_to_write or {},
                corrected_facts=corrected_facts or {},
                facts_requiring_confirmation={},
                facts_to_leave_unchanged=["CREDITO"],
            ),
            "trace_reasoning_summary": "Primary canary contract test.",
            "plan": plan,
        }
    )


def _brain_input(
    *,
    user_message: str,
    contact_fields: dict | None = None,
    extracted_data: dict | None = None,
    missing_contact_fields: list[str] | None = None,
    seniority_evidence: str | None = None,
    last_quote_signature: str | None = None,
    active_quote: dict | None = None,
    requirements_context: dict | None = None,
    documents_state: dict | None = None,
    recent_history: list[str] | None = None,
    last_bot_message: str | None = None,
    last_bot_question: str | None = None,
    business_rules: dict | None = None,
    catalog_context: dict | None = None,
    attachment_count: int = 0,
) -> AdvisorBrainInput:
    fields = dict(contact_fields or {})
    extracted = dict(extracted_data or fields)
    default_business_rules = {
        "catalog_url": "https://dinamomotos.com/catalogo.html",
        "credit_plan_options": [
            {
                "selection_key": "Nomina Tarjeta",
                "selection_label": "Nomina Tarjeta",
                "plan": "10%",
                "menu_index": 1,
                "menu_prompt": "Me depositan nomina en tarjeta",
                "aliases": ["1", "nomina tarjeta", "nomina en tarjeta", "me depositan nomina"],
            },
            {
                "selection_key": "Nomina Recibos",
                "selection_label": "Nomina Recibos",
                "plan": "15%",
                "menu_index": 2,
                "menu_prompt": "Me pagan con recibos de nomina",
                "aliases": ["2", "nomina recibos", "recibos de nomina", "me pagan con recibos"],
            },
            {
                "selection_key": "Pensionados",
                "selection_label": "Pensionados",
                "plan": "10%",
                "menu_index": 3,
                "menu_prompt": "Soy pensionado",
                "aliases": ["3", "pensionado", "soy pensionado"],
            },
            {
                "selection_key": "Negocio SAT",
                "selection_label": "Negocio SAT",
                "plan": "15%",
                "menu_index": 4,
                "menu_prompt": "Tengo negocio registrado en SAT",
                "aliases": ["4", "negocio sat", "tengo negocio", "sat"],
            },
            {
                "selection_key": "Sin Comprobantes",
                "selection_label": "Sin Comprobantes",
                "plan": "20%",
                "menu_index": 5,
                "menu_prompt": "Me pagan sin comprobantes",
                "aliases": ["5", "sin comprobantes", "me pagan por fuera", "por fuera"],
            },
            {
                "selection_key": "Guardia de Seguridad",
                "selection_label": "Guardia de Seguridad",
                "plan": "30%",
                "menu_index": 6,
                "menu_prompt": "Soy guardia de seguridad",
                "aliases": ["6", "guardia", "guardia de seguridad"],
            },
        ],
    }
    merged_business_rules = {**default_business_rules, **(business_rules or {})}
    return AdvisorBrainInput.model_validate(
        {
            "tenant_id": "tenant-test",
            "agent_name": "Francisco",
            "agent_persona": "Francisco Esparza, asesor humano de Dinamo Motos NL.",
            "user_message": user_message,
            "recent_history": recent_history or [],
            "conversation_summary": None,
            "current_stage": "nuevos",
            "last_bot_message": last_bot_message,
            "last_bot_question": last_bot_question or last_bot_message,
            "extracted_data": extracted,
            "contact_fields": fields,
            "missing_contact_fields": list(missing_contact_fields or []),
            "pending_field": None,
            "seniority_evidence": seniority_evidence,
            "active_quote": active_quote,
            "last_quote_signature": last_quote_signature,
            "catalog_context": catalog_context or {"catalog_url": "https://dinamomotos.com/catalogo.html"},
            "credit_options": [],
            "requirements_context": requirements_context or {},
            "documents_state": documents_state or {},
            "attachment_context": {"attachment_count": attachment_count},
            "operational_risk_flags": [],
            "business_rules": (
                {
                    **merged_business_rules,
                    **(
                        {"history_memory_hints": {"seniority_mentioned_in_history": seniority_evidence}}
                        if seniority_evidence
                        else {}
                    ),
                }
            ),
            "hard_guardrails": [],
        }
    )


async def _run_brain_with_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    input_payload: AdvisorBrainInput,
    llm_payload: dict,
) -> AdvisorBrainResult:
    brain = AdvisorBrain(api_key="test-key", use_local_fallback=False)

    async def _fake_invoke(_: AdvisorBrainInput) -> str:
        return json.dumps(llm_payload, ensure_ascii=False)

    monkeypatch.setattr(brain, "_invoke_llm_content", _fake_invoke)
    return await brain.run(
        input=input_payload,
        mode=AdvisorBrainMode.PRIMARY,
        final_response_source="current_runner",
    )


def test_primary_canary_allowlist_requires_target_customer_or_test_marker() -> None:
    config = advisor_brain_feature_config(
        {
            "advisor_brain": {
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": ["tenant-1"],
                "allowed_contact_ids": ["contact-1"],
                "allowed_phone_numbers": ["+5215550001111"],
            }
        }
    )

    allowed, reason = advisor_brain_canary_allowed(
        feature_config=config,
        tenant_id="tenant-1",
        customer_id="contact-1",
        phone_e164="+5215559990000",
        customer_attrs={},
        customer_tags=[],
    )
    assert allowed is True
    assert reason == "contact_id_allowlisted"

    denied, denied_reason = advisor_brain_canary_allowed(
        feature_config=config,
        tenant_id="tenant-1",
        customer_id="contact-9",
        phone_e164="+5215559990000",
        customer_attrs={},
        customer_tags=[],
    )
    assert denied is False
    assert denied_reason == "customer_not_allowlisted"


def test_manual_whatsapp_normalize_attrs_none_returns_empty_dict() -> None:
    harness = _load_manual_whatsapp_test_module()
    assert harness.normalize_attrs(None) == {}


def test_manual_whatsapp_normalize_attrs_dict_preserves_keys() -> None:
    harness = _load_manual_whatsapp_test_module()
    raw = {"legacy": "value", "nested": {"x": 1}}
    assert harness.normalize_attrs(raw) == raw


def test_manual_whatsapp_normalize_attrs_valid_json_string_returns_dict() -> None:
    harness = _load_manual_whatsapp_test_module()
    assert harness.normalize_attrs('{"legacy": "value"}') == {"legacy": "value"}


def test_manual_whatsapp_normalize_attrs_non_json_string_does_not_fail() -> None:
    harness = _load_manual_whatsapp_test_module()
    assert harness.normalize_attrs("legacy=value") == {
        harness.MANUAL_TEST_ORIGINAL_ATTRS_KEY: "legacy=value"
    }


def test_manual_whatsapp_normalize_attrs_invalid_list_does_not_fail() -> None:
    harness = _load_manual_whatsapp_test_module()
    assert harness.normalize_attrs(["legacy", "value"]) == {
        harness.MANUAL_TEST_ORIGINAL_ATTRS_KEY: ["legacy", "value"]
    }


@pytest.mark.asyncio
async def test_manual_whatsapp_prepare_normalizes_existing_non_dict_attrs_without_failing() -> None:
    harness = _load_manual_whatsapp_test_module()
    runner = object.__new__(harness.ManualWhatsAppTestRunner)
    captured: dict[str, object] = {}
    existing_row = {
        "id": "customer-1",
        "name": "Cliente Util",
        "attrs": "legacy=value",
        "tags": ["vip"],
        "stage": "qualified",
    }

    async def _find_customer_by_phone(phone_e164: str):
        assert phone_e164 == "+5218128889241"
        return existing_row

    async def _request(method: str, path: str, *, json_body=None, csrf: bool = False, params=None):
        del params
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["csrf"] = csrf
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"id": "customer-1", "name": "Cliente Util", "phone_e164": "+5218128889241"},
        )

    runner._find_customer_by_phone = _find_customer_by_phone
    runner._request = _request

    customer, previous_customer_state, normalized_from_type = await harness.ManualWhatsAppTestRunner.ensure_test_customer(
        runner,
        "+5218128889241",
        "Operador Test Client",
    )

    assert customer["id"] == "customer-1"
    assert normalized_from_type == "str"
    assert previous_customer_state == {
        "customer_id": "customer-1",
        "name": "Cliente Util",
        "stage": "qualified",
        "tags": ["vip"],
        "attrs_raw": "legacy=value",
    }
    assert captured["method"] == "PATCH"
    assert captured["path"] == f"{harness.CUSTOMERS_ENDPOINT}/customer-1"
    assert captured["csrf"] is True
    assert captured["json_body"] == {
        "name": "Cliente Util",
        "attrs": {
            harness.MANUAL_TEST_ORIGINAL_ATTRS_KEY: "legacy=value",
            "TEST_CLIENT": True,
            "NO_REAL_CUSTOMER": True,
            "MANUAL_WHATSAPP_CANARY": True,
            "manual_whatsapp_test_started_at": captured["json_body"]["attrs"]["manual_whatsapp_test_started_at"],
        },
        "tags": ["MANUAL_WHATSAPP_CANARY", "NO_REAL_CUSTOMER", "TEST_CLIENT", "vip"],
    }


@pytest.mark.asyncio
async def test_manual_whatsapp_prepare_configures_allowlist_only_for_target_customer_and_phone() -> None:
    harness = _load_manual_whatsapp_test_module()
    runner = object.__new__(harness.ManualWhatsAppTestRunner)
    runner.db = SimpleNamespace(execute=AsyncMock(return_value="UPDATE 1"))
    runner.tenant_id = "tenant-1"

    async def _tenant_row():
        return {
            "id": "tenant-1",
            "name": "Dinamo Motos NL",
            "config": {
                "advisor_brain": {
                    "enabled": False,
                    "mode": "shadow",
                    "canary": True,
                    "allowed_tenant_ids": ["other-tenant"],
                    "allowed_contact_ids": ["other-contact"],
                    "allowed_phone_numbers": ["+5215550001111"],
                }
            },
        }

    runner.tenant_row = _tenant_row

    previous, current = await harness.ManualWhatsAppTestRunner.configure_primary_canary(
        runner,
        customer_id="customer-1",
        phone_e164="+5218128889241",
    )

    assert previous == {
        "enabled": False,
        "mode": "shadow",
        "canary": True,
        "allowed_tenant_ids": ["other-tenant"],
        "allowed_contact_ids": ["other-contact"],
        "allowed_phone_numbers": ["+5215550001111"],
    }
    assert current["enabled"] is True
    assert current["mode"] == "primary"
    assert current["canary"] is True
    assert current["allowed_tenant_ids"] == ["tenant-1"]
    assert current["allowed_contact_ids"] == ["customer-1"]
    assert current["allowed_phone_numbers"] == ["+5218128889241"]


@pytest.mark.asyncio
async def test_manual_whatsapp_rollback_restores_customer_snapshot() -> None:
    harness = _load_manual_whatsapp_test_module()
    runner = object.__new__(harness.ManualWhatsAppTestRunner)
    db = SimpleNamespace(
        fetchrow=AsyncMock(return_value={"config": {"advisor_brain": {"enabled": True}}}),
        execute=AsyncMock(side_effect=["UPDATE 1", "UPDATE 1"]),
    )
    runner.db = db

    monkeypatch_state = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "previous_advisor_brain_config": {"enabled": False, "mode": "shadow"},
        "previous_customer_state": {
            "customer_id": "00000000-0000-0000-0000-000000000002",
            "name": "Cliente Util",
            "stage": "qualified",
            "tags": ["vip"],
            "attrs_raw": ["legacy", "value"],
        },
    }

    original_load_state = harness.load_state
    harness.load_state = lambda: monkeypatch_state
    try:
        result = await harness.ManualWhatsAppTestRunner.rollback_primary_canary(runner)
    finally:
        harness.load_state = original_load_state

    assert result["tenant_id"] == monkeypatch_state["tenant_id"]
    assert result["restored_advisor_brain"] == {"enabled": False, "mode": "shadow"}
    assert result["restored_customer_id"] == "00000000-0000-0000-0000-000000000002"
    assert db.execute.await_count == 2
    customer_restore_call = db.execute.await_args_list[1]
    assert json.loads(customer_restore_call.args[3]) == ["legacy", "value"]
    assert json.loads(customer_restore_call.args[4]) == ["vip"]


@pytest.mark.asyncio
async def test_manual_whatsapp_collect_resolves_conversation_from_phone_variant() -> None:
    harness = _load_manual_whatsapp_test_module()
    runner = object.__new__(harness.ManualWhatsAppTestRunner)
    prepared_at = datetime(2026, 5, 28, 1, 30, tzinfo=UTC)

    async def _customer_by_id(customer_id: str):
        assert customer_id == "customer-prepared"
        return {
            "id": "customer-prepared",
            "phone_e164": "+528128889241",
            "name": "Operador Test Client",
            "attrs": {"TEST_CLIENT": True},
            "tags": ["TEST_CLIENT"],
            "stage": "new",
            "created_at": prepared_at,
            "updated_at": prepared_at,
        }

    async def _latest_conversation_for_customer(customer_id: str):
        if customer_id == "customer-real":
            return {
                "id": "conversation-real",
                "customer_id": "customer-real",
                "status": "active",
                "current_stage": "credito",
                "created_at": prepared_at,
                "last_activity_at": prepared_at,
                "tags": [],
            }
        return None

    async def _customers_by_phone(phone_e164: str):
        if phone_e164 == "+5218128889241":
            return [
                {
                    "id": "customer-real",
                    "phone_e164": "+5218128889241",
                    "name": None,
                    "attrs": {},
                    "tags": [],
                    "stage": "new",
                    "created_at": prepared_at,
                    "updated_at": prepared_at,
                }
            ]
        if phone_e164 == "+528128889241":
            return [
                {
                    "id": "customer-prepared",
                    "phone_e164": "+528128889241",
                    "name": "Operador Test Client",
                    "attrs": {"TEST_CLIENT": True},
                    "tags": ["TEST_CLIENT"],
                    "stage": "new",
                    "created_at": prepared_at,
                    "updated_at": prepared_at,
                }
            ]
        return []

    async def _get_messages(conversation_id: str):
        assert conversation_id == "conversation-real"
        return [
            {
                "direction": "inbound",
                "body": "Hola",
                "sent_at": prepared_at.isoformat(),
            }
        ]

    runner.customer_by_id = _customer_by_id
    runner.latest_conversation_for_customer = _latest_conversation_for_customer
    runner.customers_by_phone = _customers_by_phone
    runner.recent_conversations = AsyncMock(return_value=[])
    runner.get_messages = _get_messages

    resolved = await harness.resolve_collect_conversation(
        runner,
        state={
            "customer_id": "customer-prepared",
            "customer_phone": "+5218128889241",
            "current_advisor_brain_config": {
                "allowed_contact_ids": ["customer-prepared"],
                "allowed_phone_numbers": ["+5218128889241"],
            },
        },
        status={
            "advisor_brain_config": {
                "allowed_contact_ids": ["customer-prepared"],
                "allowed_phone_numbers": ["+5218128889241"],
            }
        },
        prepared_at=prepared_at,
    )

    assert resolved["conversation"]["id"] == "conversation-real"
    assert resolved["lookup_strategy"] == "phone_lookup"
    assert resolved["found_customer_id"] == "customer-real"
    assert resolved["found_phone_e164"] == "+5218128889241"
    assert resolved["searched_phone_numbers"] == ["+5218128889241", "+528128889241"]


@pytest.mark.asyncio
async def test_manual_whatsapp_collect_falls_back_to_recent_tenant_scan() -> None:
    harness = _load_manual_whatsapp_test_module()
    runner = object.__new__(harness.ManualWhatsAppTestRunner)
    prepared_at = datetime(2026, 5, 28, 1, 30, tzinfo=UTC)

    async def _customer_by_id(customer_id: str):
        assert customer_id == "customer-prepared"
        return {
            "id": "customer-prepared",
            "phone_e164": "+528128889241",
            "name": "Operador Test Client",
            "attrs": {"TEST_CLIENT": True},
            "tags": ["TEST_CLIENT"],
            "stage": "new",
            "created_at": prepared_at,
            "updated_at": prepared_at,
        }

    async def _get_messages(conversation_id: str):
        assert conversation_id == "conversation-recent"
        return [
            {
                "direction": "inbound",
                "body": "Que modelos tienes",
                "sent_at": prepared_at.isoformat(),
            }
        ]

    runner.customer_by_id = _customer_by_id
    runner.latest_conversation_for_customer = AsyncMock(return_value=None)
    runner.customers_by_phone = AsyncMock(return_value=[])
    runner.recent_conversations = AsyncMock(
        return_value=[
            {
                "id": "conversation-recent",
                "customer_id": "customer-recent",
                "status": "active",
                "current_stage": "credito",
                "created_at": prepared_at,
                "last_activity_at": prepared_at,
                "tags": [],
                "customer_phone_e164": "+5218128889241",
                "customer_name": None,
            }
        ]
    )
    runner.get_messages = _get_messages

    resolved = await harness.resolve_collect_conversation(
        runner,
        state={
            "customer_id": "customer-prepared",
            "customer_phone": "+5218128889241",
            "current_advisor_brain_config": {
                "allowed_contact_ids": ["customer-prepared"],
                "allowed_phone_numbers": ["+5218128889241"],
            },
        },
        status={
            "advisor_brain_config": {
                "allowed_contact_ids": ["customer-prepared"],
                "allowed_phone_numbers": ["+5218128889241"],
            }
        },
        prepared_at=prepared_at,
    )

    assert resolved["conversation"]["id"] == "conversation-recent"
    assert resolved["lookup_strategy"] == "tenant_recent_scan"
    assert resolved["found_customer_id"] == "customer-recent"
    assert resolved["found_phone_e164"] == "+5218128889241"


def test_manual_whatsapp_collect_diagnosis_marks_outbox_failure_after_brain_response() -> None:
    harness = _load_manual_whatsapp_test_module()
    diagnosis = harness.diagnose_collect_delivery(
        conversation={"id": "conversation-real"},
        messages=[
            {
                "direction": "inbound",
                "body": "Que modelos tienes",
                "sent_at": "2026-05-28T01:34:37+00:00",
            }
        ],
        turns=[
            {
                "turn_number": 1,
                "final_response_source": "advisor_brain",
                "advisor_brain_llm_error": None,
                "advisor_brain_validation_error": None,
                "outbound_messages": ["Ya tengo tu perfil. Ahora dime que modelo te interesa."],
            }
        ],
        outbox_rows=[
            {
                "idempotency_key": "out:conversation-real:1:0",
                "status": "failed",
                "last_error": "transport_error_baileys:timeout",
            }
        ],
    )

    assert diagnosis["last_turn_final_response_group"] == "advisor_brain"
    assert diagnosis["last_turn_delivery_source"] == "outbox"
    assert diagnosis["last_turn_delivery_status"] == "failed"
    assert diagnosis["last_turn_outbox_status"] == "failed"


def test_manual_whatsapp_collect_diagnosis_marks_backend_when_brain_has_text_but_no_outbound() -> None:
    harness = _load_manual_whatsapp_test_module()
    diagnosis = harness.diagnose_collect_delivery(
        conversation={"id": "conversation-real"},
        messages=[
            {
                "direction": "inbound",
                "body": "Que modelos tienes",
                "sent_at": "2026-05-28T01:34:37+00:00",
            }
        ],
        turns=[
            {
                "final_response_source": "advisor_brain",
                "advisor_brain_llm_error": None,
                "advisor_brain_validation_error": None,
                "advisor_brain_natural_response": "Te comparto los modelos disponibles.",
                "outbound_blocked_reason": "duplicate_outbound",
                "duplicate_outbound_detected": True,
                "duplicate_outbound_override_attempted": False,
                "duplicate_outbound_override_applied": False,
                "outbound_policy_final_decision": "suppressed",
                "outbound_suppressed_final_reason": "duplicate_outbound",
                "trace_errors": [{"where": "outbound_policy", "reason": "duplicate_outbound"}],
                "outbound_messages": [],
            }
        ],
        outbox_rows=[],
    )

    assert diagnosis["last_turn_final_response_group"] == "advisor_brain"
    assert diagnosis["last_turn_delivery_source"] == "backend"
    assert diagnosis["last_turn_delivery_status"] == "brain_response_not_materialized"
    assert diagnosis["last_turn_outbox_row_created"] is False
    assert diagnosis["last_turn_outbox_validation_status"] == "not_created"
    assert diagnosis["last_turn_backend_exception"] == "duplicate_outbound"


@pytest.mark.asyncio
async def test_primary_duplicate_outbound_is_materialized_for_advisor_brain_response() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        session.add(
            MessageRow(
                id=uuid4(),
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                direction="outbound",
                text="Ya tengo tu perfil. Ahora dime que modelo te interesa.",
                channel_message_id="wamid.primary.prev",
                delivery_status="sent",
                metadata_json={"source": "pytest_previous_outbound"},
                sent_at=started_at,
            )
        )
        await session.flush()
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    natural_response="Ya tengo tu perfil. Ahora dime que modelo te interesa.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        inbound_id = uuid4()
        session.add(
            MessageRow(
                id=inbound_id,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                direction="inbound",
                text="Que modelos tienes",
                channel_message_id="wamid.primary.inbound",
                delivery_status="received",
                metadata_json={"source": "pytest_primary"},
                sent_at=started_at,
            )
        )
        await session.flush()

        trace = await runner.run_turn(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            inbound=Message(
                id=str(inbound_id),
                conversation_id=str(conversation_id),
                tenant_id=str(tenant_id),
                direction=MessageDirection.INBOUND,
                text="Que modelos tienes",
                sent_at=started_at,
                metadata={"source": "pytest_primary"},
            ),
            turn_number=2,
            arq_pool=object(),
            to_phone_e164="+5215550001111",
        )

        outbox_rows = (
            await session.execute(
                select(OutboundOutbox).where(OutboundOutbox.tenant_id == tenant_id)
            )
        ).scalars().all()

        assert trace.state_after["final_response_source"] == "advisor_brain"
        assert trace.state_after["advisor_brain_primary_used"] is True
        assert trace.state_after["outbound_blocked_reason"] is None
        assert trace.state_after["duplicate_outbound_detected"] is True
        assert trace.state_after["duplicate_outbound_override_attempted"] is True
        assert trace.state_after["duplicate_outbound_override_applied"] is True
        assert trace.state_after["outbound_policy_final_decision"] == "allowed"
        assert trace.state_after["outbound_suppressed_final_reason"] is None
        assert (
            trace.state_after["outbound_policy_override_reason"]
            == "duplicate_outbound_bypassed_for_advisor_brain_primary"
        )
        assert trace.outbound_messages == ["Ya tengo tu perfil. Ahora dime que modelo te interesa."]
        assert trace.errors is None
        assert len(outbox_rows) == 1
        payload = outbox_rows[0].payload
        assert payload["idempotency_key"] == f"out:{conversation_id}:2:0"
        assert OutboundMessage.model_validate(payload).to_phone_e164 == "+5215550001111"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_only_activates_for_allowlist_and_uses_brain_response() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    natural_response="Ya tengo tu perfil. Ahora dime que modelo te interesa.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola",
        )

        assert trace.outbound_messages == ["Ya tengo tu perfil. Ahora dime que modelo te interesa."]
        assert trace.state_after["final_response_source"] == "advisor_brain"
        assert trace.state_after["advisor_brain_canary_allowed"] is True
        assert trace.state_after["advisor_brain_primary_used"] is True
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_outside_allowlist_keeps_current_runner_response() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550002222",
            attrs={},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(uuid4())],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    natural_response="Este texto no debe salir porque no esta allowlisted.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola",
        )

        assert trace.outbound_messages == ["Claro, te ayudo. Dime que modelo te interesa."]
        assert trace.state_after["final_response_source"] == "current_runner"
        assert trace.state_after["advisor_brain_canary_allowed"] is False
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_falls_back_to_runner_if_brain_fails() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=None,
                llm_error="RuntimeError: timeout",
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola",
        )

        assert trace.outbound_messages == ["Claro, te ayudo. Dime que modelo te interesa."]
        assert trace.state_after["final_response_source"] == "current_runner"
        assert trace.state_after["advisor_brain_llm_error"] == "RuntimeError: timeout"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_canary_runner_authority_prefers_advisor_brain_for_missing_seniority() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={},
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_seniority",
                    detected_intent="collect_seniority",
                    natural_response="Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.outbound_messages == [
            "Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual."
        ]
        assert trace.state_after["advisor_brain_primary_used"] is True
        assert trace.state_after["runner_decision_source"] == "advisor_brain"
        assert trace.state_after["commercial_flow_step"] == "ask_seniority"
        assert trace.state_after["legacy_sales_policy_decision"] == "ask_income_type"
        assert trace.state_after["legacy_sales_policy_suppressed_by_advisor_brain"] is True
        assert trace.state_after["final_action_source"] == "advisor_brain"
        assert trace.state_after["final_action"] == "ask_seniority"
        assert trace.state_after["final_action_payload"]["request_type"] == "ask_employment_seniority"
        assert trace.state_after["final_action_payload"]["field_name"] == "ANTIGUEDAD_LABORAL"
        assert trace.state_after["final_action_payload"].get("field_alias") == "employment_seniority"
        assert trace.state_after["final_action"] != "ask_credit_context"
        assert trace.state_after["final_action_payload"]["field_name"] != "CREDITO"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_canary_runner_authority_falls_back_to_legacy_sales_policy_when_brain_fails() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={},
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=None,
                llm_error="RuntimeError: timeout",
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["advisor_brain_primary_used"] is False
        assert trace.state_after["runner_decision_source"] == "sales_advisor_policy"
        assert trace.state_after["legacy_sales_policy_decision"] == "ask_income_type"
        assert trace.state_after["legacy_sales_policy_suppressed_by_advisor_brain"] is False
        assert trace.state_after["final_action_source"] == "sales_advisor_policy"
        assert trace.state_after["final_action"] == "ask_credit_context"
        assert trace.state_after["final_action_payload"]["field_name"] == "CREDITO"
        assert trace.state_after["final_action_payload"]["request_type"] == "ask_income_type"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_canary_runner_authority_advances_to_credit_plan_when_seniority_is_known() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={
                "ANTIGUEDAD_LABORAL": {"value": "2 anos", "confidence": 0.9, "source_turn": 0},
                "FILTRO": {"value": "true", "confidence": 0.9, "source_turn": 0},
                "CUMPLE_ANTIGUEDAD": {"value": True, "confidence": 0.9, "source_turn": 0},
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="resolve_credit_plan",
                    detected_intent="resolve_credit_plan",
                    natural_response="Perfecto. Ahora te digo las opciones de plan para tu credito.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["advisor_brain_primary_used"] is True
        assert trace.state_after["runner_decision_source"] == "advisor_brain"
        assert trace.state_after["commercial_flow_step"] == "resolve_credit_plan"
        assert trace.state_after["final_action_source"] == "advisor_brain"
        assert trace.state_after["final_action"] == "ask_credit_context"
        assert trace.state_after["final_action_payload"]["field_name"] == "CREDITO"
        assert trace.state_after["final_action_payload"]["request_type"] == "ask_income_type"
        assert trace.state_after["final_action"] != "ask_seniority"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_case_001_quotes_when_model_and_pension_plan_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Pensionado",
        contact_fields={"MOTO": "Renegada 250 CC", "CREDITO": "Pensionados", "ENGANCHE": "10%"},
        missing_contact_fields=[],
        recent_history=["inbound: Hola me interesa la moto de la foto", "inbound: Renegada"],
        last_bot_message="Ya tengo la Renegada. Ahora dime como recibes tus ingresos.",
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente eligio Renegada y perfil Pensionados.",
            "conversation_memory_used": ["MOTO=Renegada 250 CC", "CREDITO=Pensionados"],
            "detected_intent": "collect_seniority",
            "known_facts": {"MOTO": "Renegada 250 CC", "CREDITO": "Pensionados", "ENGANCHE": "10%"},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": ["ANTIGUEDAD_LABORAL"],
            "next_human_step": "ask_seniority",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Dime cuanto tiempo llevas trabajando.",
            "confidence": 0.88,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": ["MOTO", "CREDITO", "ENGANCHE"],
            },
            "trace_reasoning_summary": "Primary quote fix.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "quote"
    assert result.output.detected_intent == "quote_request"
    assert result.output.tool_requests[0].tool_name == "compute_quote"
    assert result.output.missing_required_facts == []


@pytest.mark.asyncio
async def test_primary_case_001_que_te_mando_after_quote_requests_first_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Que te mando?",
        contact_fields={"MOTO": "Renegada 250 CC", "CREDITO": "Pensionados", "ENGANCHE": "10%"},
        last_quote_signature="renegada 250 cc 10%",
        requirements_context={
            "selection_key": "Pensionados",
            "required": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
        },
        documents_state={
            "selection_key": "Pensionados",
            "missing": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
        },
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente quiere avanzar con documentos.",
            "conversation_memory_used": ["Ultima cotizacion vigente"],
            "detected_intent": "requirements_request",
            "known_facts": {"MOTO": "Renegada 250 CC", "CREDITO": "Pensionados", "ENGANCHE": "10%"},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "requirements",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Te digo los requisitos.",
            "confidence": 0.92,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": ["MOTO", "CREDITO", "ENGANCHE"],
            },
            "trace_reasoning_summary": "Primary documents fix.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_first_missing_document"
    assert result.output.detected_intent == "send_documents_request"
    assert result.output.tool_requests[0].tool_name == "get_missing_documents"


@pytest.mark.asyncio
async def test_primary_case_002_keeps_model_while_requesting_seniority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Quiero la R4",
        contact_fields={"MOTO": "R4 250 CC", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
        missing_contact_fields=["ANTIGUEDAD_LABORAL"],
        recent_history=["inbound: Hola, quiero credito", "inbound: Me pagan por fuera"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente quiere la R4 con plan Sin Comprobantes.",
            "conversation_memory_used": ["MOTO=R4 250 CC", "CREDITO=Sin Comprobantes"],
            "detected_intent": "requirements_request",
            "known_facts": {"MOTO": "R4 250 CC", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "explain_required_documents",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Mandame tus documentos.",
            "confidence": 0.85,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": ["MOTO", "CREDITO", "ENGANCHE"],
            },
            "trace_reasoning_summary": "Primary seniority fix.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_seniority"
    assert "R4 250 CC" in result.output.natural_response
    assert "ANTIGUEDAD_LABORAL" in result.output.missing_required_facts


@pytest.mark.asyncio
async def test_primary_case_002_quotes_after_seniority_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Tengo 2 anos",
        contact_fields={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "ANTIGUEDAD_LABORAL": "2 anos",
            "FILTRO": "true",
        },
        seniority_evidence="Tengo 2 anos",
        missing_contact_fields=[],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente ya dio antiguedad y quiere seguir.",
            "conversation_memory_used": ["MOTO=R4 250 CC", "CREDITO=Sin Comprobantes"],
            "detected_intent": "requirements_request",
            "known_facts": {
                "MOTO": "R4 250 CC",
                "CREDITO": "Sin Comprobantes",
                "ENGANCHE": "20%",
                "ANTIGUEDAD_LABORAL": "2 anos",
            },
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": ["ANTIGUEDAD_LABORAL"],
            "next_human_step": "explain_required_documents",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Mandame documentos.",
            "confidence": 0.9,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": ["MOTO", "CREDITO", "ENGANCHE", "ANTIGUEDAD_LABORAL"],
            },
            "trace_reasoning_summary": "",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "quote"
    assert result.output.detected_intent == "quote_request"
    assert result.output.tool_requests[0].tool_name == "compute_quote"
    assert "ANTIGUEDAD_LABORAL" not in result.output.missing_required_facts
    assert result.validation_error is None


@pytest.mark.asyncio
async def test_primary_case_002_soft_close_after_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Gracias, lo veo",
        contact_fields={"MOTO": "R4 250 CC", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
        last_quote_signature="r4 250 cc 20%",
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente cierra suave despues de la quote.",
            "conversation_memory_used": ["Ultima cotizacion vigente"],
            "detected_intent": "close",
            "known_facts": {"MOTO": "R4 250 CC", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "close",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Perfecto.",
            "confidence": 0.91,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": ["MOTO", "CREDITO", "ENGANCHE"],
            },
            "trace_reasoning_summary": "Primary soft close fix.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "soft_close"
    assert result.output.tool_requests == []


@pytest.mark.asyncio
async def test_primary_flow_new_lead_asks_seniority_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(user_message="Hola quiero una moto a credito")
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente quiere una moto.",
            "conversation_memory_used": [],
            "detected_intent": "collect_model",
            "known_facts": {},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": ["MOTO"],
            "next_human_step": "resolve_model",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Dime que modelo te interesa.",
            "confidence": 0.81,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": [],
            },
            "trace_reasoning_summary": "Flow order test.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_seniority"
    assert "cuanto tiempo" in result.output.natural_response.casefold()
    assert "modelo" not in result.output.natural_response.casefold()
    assert "document" not in result.output.natural_response.casefold()
    assert "ANTIGUEDAD_LABORAL" in result.output.missing_required_facts


@pytest.mark.asyncio
async def test_primary_flow_after_seniority_shows_plan_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(user_message="Tengo 2 anos")
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente ya dio antiguedad.",
            "conversation_memory_used": [],
            "detected_intent": "collect_model",
            "known_facts": {},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": ["MOTO"],
            "next_human_step": "resolve_model",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Dime que modelo te interesa.",
            "confidence": 0.85,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": [],
            },
            "trace_reasoning_summary": "Flow order test.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_credit_plan"
    rendered = result.output.natural_response.casefold()
    expected_lines = [
        "1. me depositan nomina en tarjeta",
        "2. me pagan con recibos de nomina",
        "3. soy pensionado",
        "4. tengo negocio registrado en sat",
        "5. me pagan sin comprobantes",
        "6. soy guardia de seguridad",
    ]
    positions = [rendered.index(line) for line in expected_lines]
    assert positions == sorted(positions)
    assert "puedes mandarme el numero" in result.output.natural_response.casefold()
    assert result.output.state_write_plan.new_facts_to_write["CUMPLE_ANTIGUEDAD"] is True
    assert result.output.state_write_plan.new_facts_to_write["ANTIGUEDAD_LABORAL"] == "Tengo 2 anos"


@pytest.mark.asyncio
async def test_primary_flow_after_plan_confirms_credit_and_requests_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="me pagan por fuera",
        contact_fields={"ANTIGUEDAD_LABORAL": "2 anos", "FILTRO": "true", "CUMPLE_ANTIGUEDAD": True},
        missing_contact_fields=["CREDITO", "ENGANCHE", "MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente quiere avanzar.",
            "conversation_memory_used": [],
            "detected_intent": "requirements_request",
            "known_facts": {},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "explain_required_documents",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Mandame documentos.",
            "confidence": 0.84,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": [],
            },
            "trace_reasoning_summary": "Flow order test.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_model"
    assert result.output.known_facts["CREDITO"] == "Sin Comprobantes"
    assert result.output.known_facts["ENGANCHE"] == "20%"
    assert "catalogo: https://dinamomotos.com/catalogo.html" in result.output.natural_response.casefold()
    assert "modelo" in result.output.natural_response.casefold()
    assert "document" not in result.output.natural_response.casefold()


@pytest.mark.asyncio
async def test_primary_flow_numeric_plan_1_maps_to_nomina_tarjeta_10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="1",
        contact_fields={"ANTIGUEDAD_LABORAL": "2 anos", "FILTRO": "true", "CUMPLE_ANTIGUEDAD": True},
        missing_contact_fields=["CREDITO", "ENGANCHE", "MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="resolve_credit_plan",
            detected_intent="resolve_credit_plan",
            natural_response="Dime como recibes tus ingresos.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_model"
    assert result.output.known_facts["CREDITO"] == "Nomina Tarjeta"
    assert result.output.known_facts["ENGANCHE"] == "10%"
    assert result.output.state_write_plan.new_facts_to_write["CREDITO"] == "Nomina Tarjeta"
    assert result.output.state_write_plan.new_facts_to_write["ENGANCHE"] == "10%"


@pytest.mark.asyncio
async def test_primary_flow_numeric_plan_6_maps_to_guardia_30(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="6",
        contact_fields={"ANTIGUEDAD_LABORAL": "2 anos", "FILTRO": "true", "CUMPLE_ANTIGUEDAD": True},
        missing_contact_fields=["CREDITO", "ENGANCHE", "MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="resolve_credit_plan",
            detected_intent="resolve_credit_plan",
            natural_response="Dime como recibes tus ingresos.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_model"
    assert result.output.known_facts["CREDITO"] == "Guardia de Seguridad"
    assert result.output.known_facts["ENGANCHE"] == "30%"
    assert result.output.state_write_plan.new_facts_to_write["CREDITO"] == "Guardia de Seguridad"
    assert result.output.state_write_plan.new_facts_to_write["ENGANCHE"] == "30%"


@pytest.mark.asyncio
async def test_primary_flow_corrects_guardia_20_to_guardia_30_before_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="6",
        contact_fields={
            "ANTIGUEDAD_LABORAL": "2 anos",
            "FILTRO": "true",
            "CUMPLE_ANTIGUEDAD": True,
            "CREDITO": "Guardia de Seguridad",
            "ENGANCHE": "20%",
        },
        missing_contact_fields=["MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="resolve_model",
            detected_intent="resolve_model",
            natural_response="Dime el modelo.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.known_facts["CREDITO"] == "Guardia de Seguridad"
    assert result.output.known_facts["ENGANCHE"] == "30%"
    assert result.output.state_write_plan.new_facts_to_write["ENGANCHE"] == "30%"


@pytest.mark.asyncio
async def test_primary_flow_after_model_goes_to_quote_not_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="speedfire",
        contact_fields={
            "ANTIGUEDAD_LABORAL": "2 anos",
            "FILTRO": "true",
            "CUMPLE_ANTIGUEDAD": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        missing_contact_fields=["MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente ya quiere enviar papeles.",
            "conversation_memory_used": [],
            "detected_intent": "requirements_request",
            "known_facts": {},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "explain_required_documents",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Mandame documentos.",
            "confidence": 0.83,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": [],
            },
            "trace_reasoning_summary": "Flow order test.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "quote"
    assert result.output.detected_intent == "quote_request"
    assert result.output.tool_requests[0].tool_name == "compute_quote"
    assert result.output.tool_requests[0].args["model"] == "speedfire"
    assert result.output.tool_requests[0].args["down_payment"] == "20%"
    assert "document" not in result.output.natural_response.casefold()


@pytest.mark.asyncio
async def test_primary_flow_after_quote_asks_only_first_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Que te mando",
        contact_fields={"MOTO": "Speedfire", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
        last_quote_signature="speedfire 20%",
        requirements_context={
            "selection_key": "Sin Comprobantes",
            "required": [
                {"key": "INE_FRENTE", "label": "INE frente"},
                {"key": "INE_ATRAS", "label": "INE atras"},
                {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
            ],
        },
        documents_state={
            "selection_key": "Sin Comprobantes",
            "missing": [
                {"key": "INE_FRENTE", "label": "INE frente"},
                {"key": "INE_ATRAS", "label": "INE atras"},
            ],
        },
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="requirements",
            detected_intent="requirements_request",
            natural_response="Te digo los requisitos.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_first_missing_document"
    assert result.output.detected_intent == "send_documents_request"
    assert result.output.natural_response == "Va, para avanzar primero mandame tu INE por ambos lados, completa y bien legible."


@pytest.mark.asyncio
async def test_primary_flow_after_quote_me_interesa_requests_ine_not_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Me interesa",
        contact_fields={"MOTO": "Custom Black 175 CC", "CREDITO": "Guardia de Seguridad", "ENGANCHE": "30%"},
        last_quote_signature="custom black 175 cc 30%",
        requirements_context={
            "selection_key": "Guardia de Seguridad",
            "required": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
        },
        documents_state={
            "selection_key": "Guardia de Seguridad",
            "missing": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
        },
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="Te repito la cotizacion.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_first_missing_document"
    assert result.output.detected_intent == "send_documents_request"
    assert result.output.natural_response == "Va, para avanzar primero mandame tu INE por ambos lados, completa y bien legible."


@pytest.mark.asyncio
async def test_primary_flow_after_quote_si_ya_me_dijiste_requests_next_step_not_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Si ya me dijiste",
        contact_fields={"MOTO": "Custom Black 175 CC", "CREDITO": "Guardia de Seguridad", "ENGANCHE": "30%"},
        last_quote_signature="custom black 175 cc 30%",
        requirements_context={
            "selection_key": "Guardia de Seguridad",
            "required": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
        },
        documents_state={
            "selection_key": "Guardia de Seguridad",
            "missing": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
        },
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="Te paso otra vez la cotizacion.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_first_missing_document"
    assert result.output.detected_intent == "quote_already_shared"
    assert (
        result.output.natural_response
        == "Tienes razon, ya te la habia pasado. Para avanzar, primero mandame tu INE por ambos lados, completa y bien legible."
    )


@pytest.mark.asyncio
async def test_primary_flow_que_ocupo_lists_requirements_then_me_interesa_requests_first_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirements_context = {
        "selection_key": "Sin Comprobantes",
        "required": [
            {"key": "INE_FRENTE", "label": "INE por ambos lados"},
            {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
        ],
    }
    documents_state = {
        "selection_key": "Sin Comprobantes",
        "missing": [{"key": "INE_FRENTE", "label": "INE por ambos lados"}],
    }
    requirements_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="Que ocupo",
            contact_fields={"MOTO": "Speedfire", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            last_quote_signature="speedfire 20%",
            requirements_context=requirements_context,
            documents_state=documents_state,
        ),
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="Te repito la cotizacion.",
        ).model_dump(mode="json"),
    )
    advance_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="Me interesa",
            contact_fields={"MOTO": "Speedfire", "CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            last_quote_signature="speedfire 20%",
            requirements_context=requirements_context,
            documents_state=documents_state,
        ),
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="Te repito la cotizacion.",
        ).model_dump(mode="json"),
    )

    assert requirements_result.output is not None
    assert requirements_result.output.next_human_step == "explain_required_documents"
    assert "ocupamos" in requirements_result.output.natural_response.casefold()
    assert advance_result.output is not None
    assert advance_result.output.next_human_step == "ask_first_missing_document"
    assert advance_result.output.natural_response == "Va, para avanzar primero mandame tu INE por ambos lados, completa y bien legible."


@pytest.mark.asyncio
async def test_primary_flow_received_ine_front_requests_ine_back_not_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="[imagen INE]",
        contact_fields={"MOTO": "Custom Black 175 CC", "CREDITO": "Guardia de Seguridad", "ENGANCHE": "30%"},
        last_quote_signature="custom black 175 cc 30%",
        requirements_context={
            "selection_key": "Guardia de Seguridad",
            "required": [
                {"key": "INE_FRENTE", "label": "INE frente"},
                {"key": "INE_ATRAS", "label": "INE atras"},
                {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
            ],
        },
        documents_state={
            "selection_key": "Guardia de Seguridad",
            "received_this_turn": [{"key": "INE_FRENTE", "label": "INE frente"}],
            "received": [{"key": "INE_FRENTE", "label": "INE frente"}],
            "missing": [
                {"key": "INE_ATRAS", "label": "INE atras"},
                {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
            ],
        },
        attachment_count=1,
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="Te repito la cotizacion.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "ask_first_missing_document"
    assert result.output.detected_intent == "document_received"
    assert result.output.natural_response == "Listo, ya recibi el frente de tu INE. Ahora mandame la parte de atras, bien legible."


@pytest.mark.asyncio
async def test_primary_live_regression_sequence_enforces_quote_and_document_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seniority_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="desde octubre del año pasado",
            recent_history=["Cliente: hola vi el anuncio"],
            missing_contact_fields=["ANTIGUEDAD_LABORAL", "CREDITO", "ENGANCHE", "MOTO"],
        ),
        llm_payload=_brain_output(
            next_human_step="resolve_credit_plan",
            detected_intent="resolve_credit_plan",
            natural_response="Dime como recibes tus ingresos.",
        ).model_dump(mode="json"),
    )
    assert seniority_result.output is not None
    assert seniority_result.output.next_human_step == "resolve_credit_plan"
    rendered_menu = seniority_result.output.natural_response.casefold()
    assert rendered_menu.index("1. me depositan nomina en tarjeta") < rendered_menu.index(
        "6. soy guardia de seguridad"
    )

    credit_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="6",
            contact_fields={"ANTIGUEDAD_LABORAL": "7 meses", "FILTRO": "true", "CUMPLE_ANTIGUEDAD": True},
            missing_contact_fields=["CREDITO", "ENGANCHE", "MOTO"],
        ),
        llm_payload=_brain_output(
            next_human_step="resolve_credit_plan",
            detected_intent="resolve_credit_plan",
            natural_response="Dime como recibes tus ingresos.",
        ).model_dump(mode="json"),
    )
    assert credit_result.output is not None
    assert credit_result.output.known_facts["CREDITO"] == "Guardia de Seguridad"
    assert credit_result.output.known_facts["ENGANCHE"] == "30%"

    model_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="rayo elite",
            contact_fields={
                "ANTIGUEDAD_LABORAL": "7 meses",
                "FILTRO": "true",
                "CUMPLE_ANTIGUEDAD": True,
                "CREDITO": "Guardia de Seguridad",
                "ENGANCHE": "30%",
            },
            missing_contact_fields=["MOTO"],
        ),
        llm_payload={
            "customer_understanding": "Cliente ya quiere mandar documentos.",
            "conversation_memory_used": [],
            "detected_intent": "requirements_request",
            "known_facts": {},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "explain_required_documents",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Mandame documentos.",
            "confidence": 0.8,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": [],
            },
            "trace_reasoning_summary": "Regression after model must quote first.",
        },
    )
    assert model_result.output is not None
    assert model_result.output.next_human_step == "quote"

    complaint_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="pero no voy a mandarte nada antes de que me digas cuanto sale",
            contact_fields={
                "ANTIGUEDAD_LABORAL": "7 meses",
                "FILTRO": "true",
                "CUMPLE_ANTIGUEDAD": True,
                "CREDITO": "Guardia de Seguridad",
                "ENGANCHE": "30%",
                "MOTO": "Rayo Elite 250 CC",
            },
            active_quote={"name": "Rayo Elite 250 CC"},
            last_quote_signature="rayo elite 250 cc 30%",
        ),
        llm_payload=_brain_output(
            next_human_step="soft_close",
            detected_intent="soft_close",
            natural_response="Va, revisalo con calma.",
        ).model_dump(mode="json"),
    )
    assert complaint_result.output is not None
    assert complaint_result.output.next_human_step == "quote"

    price_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="cuanto cuesta la rayo elite",
            contact_fields={
                "ANTIGUEDAD_LABORAL": "7 meses",
                "FILTRO": "true",
                "CUMPLE_ANTIGUEDAD": True,
                "CREDITO": "Guardia de Seguridad",
                "ENGANCHE": "30%",
                "MOTO": "Rayo Elite 250 CC",
            },
            active_quote={"name": "Rayo Elite 250 CC"},
            last_quote_signature="rayo elite 250 cc 30%",
        ),
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="Te paso el precio de contado.",
        ).model_dump(mode="json"),
    )
    assert price_result.output is not None
    assert price_result.output.next_human_step == "quote"

    document_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="[pdf ine]",
            contact_fields={
                "ANTIGUEDAD_LABORAL": "7 meses",
                "FILTRO": "true",
                "CUMPLE_ANTIGUEDAD": True,
                "CREDITO": "Guardia de Seguridad",
                "ENGANCHE": "30%",
                "MOTO": "Rayo Elite 250 CC",
            },
            active_quote={"name": "Rayo Elite 250 CC"},
            last_quote_signature="rayo elite 250 cc 30%",
            requirements_context={
                "selection_key": "Guardia de Seguridad",
                "required": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
                ],
                "received": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                ],
                "missing": [
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"}
                ],
            },
            documents_state={
                "selection_key": "Guardia de Seguridad",
                "received_this_turn": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                ],
                "received": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                ],
                "missing": [
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"}
                ],
            },
            attachment_count=1,
        ),
        llm_payload=_brain_output(
            next_human_step="ask_first_missing_document",
            detected_intent="document_received",
            natural_response="Listo, ya recibi tu INE.",
        ).model_dump(mode="json"),
    )
    assert document_result.output is not None
    assert document_result.output.next_human_step == "ask_first_missing_document"

    down_payment_result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=_brain_input(
            user_message="cuanto es de enganche",
            contact_fields={
                "ANTIGUEDAD_LABORAL": "7 meses",
                "FILTRO": "true",
                "CUMPLE_ANTIGUEDAD": True,
                "CREDITO": "Guardia de Seguridad",
                "ENGANCHE": "30%",
                "MOTO": "Rayo Elite 250 CC",
            },
            active_quote={"name": "Rayo Elite 250 CC"},
            last_quote_signature="rayo elite 250 cc 30%",
        ),
        llm_payload=_brain_output(
            next_human_step="quote",
            detected_intent="quote_request",
            natural_response="El enganche es 30%.",
        ).model_dump(mode="json"),
    )
    assert down_payment_result.output is not None
    assert down_payment_result.output.next_human_step == "quote"


@pytest.mark.asyncio
async def test_primary_flow_catalog_request_shares_catalog_not_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="que motos tienes",
        contact_fields={
            "ANTIGUEDAD_LABORAL": "2 anos",
            "FILTRO": "true",
            "CUMPLE_ANTIGUEDAD": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        missing_contact_fields=["MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="explain_required_documents",
            detected_intent="requirements_request",
            natural_response="Mandame documentos.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_model"
    assert "catalogo: https://dinamomotos.com/catalogo.html" in result.output.natural_response.casefold()
    assert "document" not in result.output.natural_response.casefold()


@pytest.mark.asyncio
async def test_primary_flow_does_not_reask_seniority_when_already_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Quiero una moto a credito",
        contact_fields={"ANTIGUEDAD_LABORAL": "2 anos", "FILTRO": "true", "CUMPLE_ANTIGUEDAD": True},
        missing_contact_fields=["CREDITO", "ENGANCHE", "MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="ask_seniority",
            detected_intent="collect_seniority",
            natural_response="Dime cuanto tiempo llevas trabajando.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_credit_plan"
    assert "cuanto tiempo" not in result.output.natural_response.casefold()
    assert "1. me depositan nomina en tarjeta" in result.output.natural_response.casefold()


@pytest.mark.asyncio
async def test_primary_flow_does_not_repeat_plan_menu_when_plan_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Quiero una moto",
        contact_fields={
            "ANTIGUEDAD_LABORAL": "2 anos",
            "FILTRO": "true",
            "CUMPLE_ANTIGUEDAD": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        missing_contact_fields=["MOTO"],
    )
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=_brain_output(
            next_human_step="resolve_credit_plan",
            detected_intent="resolve_credit_plan",
            natural_response="Para ver tu plan dime como recibes tus ingresos.",
        ).model_dump(mode="json"),
    )

    assert result.output is not None
    assert result.output.next_human_step == "resolve_model"
    assert "como recibes tus ingresos" not in result.output.natural_response.casefold()
    assert "catalogo: https://dinamomotos.com/catalogo.html" in result.output.natural_response.casefold()


@pytest.mark.asyncio
async def test_primary_sensitive_payment_forces_handoff_even_if_llm_drifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(user_message="Ya di enganche")
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload={
            "customer_understanding": "Cliente quiere seguir con credito.",
            "conversation_memory_used": [],
            "detected_intent": "resolve_credit_plan",
            "known_facts": {},
            "new_facts_to_write": {},
            "corrected_facts": {},
            "missing_required_facts": [],
            "next_human_step": "resolve_credit_plan",
            "tool_requests": [],
            "forbidden_actions": [],
            "natural_response": "Dime como recibes tus ingresos.",
            "confidence": 0.8,
            "handoff_required": False,
            "handoff_reason": None,
            "state_write_plan": {
                "new_facts_to_write": {},
                "corrected_facts": {},
                "facts_requiring_confirmation": {},
                "facts_to_leave_unchanged": [],
            },
            "trace_reasoning_summary": "Sensitive handoff fix.",
        },
    )

    assert result.output is not None
    assert result.output.next_human_step == "handoff"
    assert result.output.handoff_required is True
    assert result.output.tool_requests[0].tool_name == "request_handoff"


@pytest.mark.asyncio
async def test_primary_guardrail_blocks_quote_without_model() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="quote",
                    natural_response="La moto queda en $55,000 con enganche $5,000.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=True,
                guardrail_reason="quote_without_model",
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola",
        )

        assert trace.state_after["final_response_source"] == "current_runner"
        assert trace.state_after["advisor_brain_guardrail_blocked"] is True
        assert trace.state_after["advisor_brain_guardrail_reason"] == "quote_without_model"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_guardrail_blocks_documents_before_quote() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="explain_required_documents",
                    detected_intent="requirements_request",
                    natural_response="Mandame tus documentos para avanzar.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola",
        )

        assert trace.state_after["final_response_source"] == "current_runner"
        assert trace.state_after["advisor_brain_guardrail_blocked"] is True
        assert trace.state_after["advisor_brain_guardrail_reason"] == "documents_before_valid_quote"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_state_write_policy_blocks_conflicting_brain_update() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            extracted_data={"MOTO": {"value": "Renegada", "confidence": 0.99, "source_turn": 0}},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="quote",
                    natural_response="La R4 queda en $55,000 con enganche $5,000.",
                    new_facts_to_write={"MOTO": "R4 250 CC"},
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola",
        )

        blocked = trace.state_after["advisor_brain_state_write_blocked"]
        assert trace.state_after["final_response_source"] == "current_runner"
        assert blocked
        assert blocked[0]["field"] == "MOTO"
        assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Renegada"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_quote_persists_canonical_motorcycle_model_and_trace_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            extracted_data={
                "CREDITO": {"value": "Guardia de Seguridad", "confidence": 0.99, "source_turn": 0},
                "ENGANCHE": {"value": "30%", "confidence": 0.99, "source_turn": 0},
            },
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )

        async def _fake_quote(self, *, tenant_id, candidate_queries, plan_code, collection_ids):
            del self, tenant_id, candidate_queries, plan_code, collection_ids
            return SimpleNamespace(
                action_payload={
                    "status": "ok",
                    "sku": "CUSTOM-BLACK-175",
                    "name": "Custom Black 175 CC",
                    "cash_price_mxn": "52700",
                    "requested_plan_code": "30%",
                    "payment_options": {
                        "30%": {
                            "down_payment_mxn": "15810",
                            "installment_mxn": "1890",
                            "term_count": 30,
                        }
                    },
                },
                tool_call_logs=[],
                executed_tools=[],
                tool_cost_usd=Decimal("0"),
            )

        monkeypatch.setattr("atendia.runner.tool_dispatch.ToolDispatch.quote", _fake_quote)
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="quote",
                    natural_response="Te cotizo la moto correcta.",
                    new_facts_to_write={"MOTO": "Black Custom"},
                ).model_copy(
                    update={
                        "tool_requests": [
                            AdvisorBrainToolRequest.model_validate(
                                {
                                    "tool_name": "compute_quote",
                                    "args": {"model": "Black Custom", "down_payment": "30%"},
                                    "reason": "Cotizar con modelo canonico.",
                                }
                            )
                        ]
                    }
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Black Custom",
        )

        await session.flush()
        persisted_state = (
            await session.execute(
                text(
                    "SELECT extracted_data FROM conversation_state WHERE conversation_id = :cid"
                ),
                {"cid": conversation_id},
            )
        ).scalar_one()
        assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Custom Black 175 CC"
        assert persisted_state["MOTO"]["value"] == "Custom Black 175 CC"
        assert trace.state_after["persisted_motorcycle_model"] == "Custom Black 175 CC"
        assert trace.state_after["contact_fields_updated"] == ["MOTO"]
        assert trace.state_after["state_consistency_errors"] == []
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_document_follow_up_keeps_stage_doc_incompleta() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            extracted_data={
                "MOTO": {"value": "Custom Black 175 CC", "confidence": 0.99, "source_turn": 0},
                "CREDITO": {"value": "Guardia de Seguridad", "confidence": 0.99, "source_turn": 0},
                "ENGANCHE": {"value": "30%", "confidence": 0.99, "source_turn": 0},
            },
            ai_summary="Ultima cotizacion: Custom Black 175 CC; plan 30%; contado $52,700; enganche $15,810; pago $1,890.",
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_first_missing_document",
                    detected_intent="document_received",
                    natural_response="Listo, ya recibi el frente de tu INE. Ahora mandame la parte de atras, bien legible.",
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Me interesa",
        )

        assert trace.state_after["current_stage"] == "doc_incompleta"
        assert trace.state_after["pipeline_stage_after_turn"] == "doc_incompleta"
        assert trace.state_after["final_action"] == "classify_document"
    finally:
        await session.rollback()
        await session.close()


async def _run_turn(
    *,
    runner: ConversationRunner,
    tenant_id,
    conversation_id,
    sent_at: datetime,
    text: str,
    attachments: list | None = None,
):
    inbound_id = uuid4()
    runner._session.add(
        MessageRow(
            id=inbound_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            direction="inbound",
            text=text,
            channel_message_id="wamid.primary.1",
            delivery_status="received",
            metadata_json={"source": "pytest_primary"},
            sent_at=sent_at,
        )
    )
    await runner._session.flush()
    return await runner.run_turn(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        inbound=Message(
            id=str(inbound_id),
            conversation_id=str(conversation_id),
            tenant_id=str(tenant_id),
            direction=MessageDirection.INBOUND,
            text=text,
            sent_at=sent_at,
            metadata={"source": "pytest_primary"},
            attachments=attachments or [],
        ),
        turn_number=1,
    )


async def _seed_primary_fixture(
    *,
    session,
    tenant_id,
    customer_id,
    conversation_id,
    created_at: datetime,
    phone_e164: str,
    attrs: dict,
    advisor_brain_config: dict,
    extracted_data: dict | None = None,
    ai_summary: str | None = None,
) -> None:
    session.add(
        Tenant(
            id=tenant_id,
            name=f"dinamo-primary-{tenant_id}",
            status="active",
            config={"advisor_brain": advisor_brain_config},
        )
    )
    await session.flush()
    session.add(
        TenantPipeline(
            tenant_id=tenant_id,
            version=1,
            active=True,
            definition={
                "version": 1,
                "fallback": "ask_clarification",
                "document_requirements_field": "CREDITO",
                "document_requirements": {
                    "Nomina Tarjeta": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                    "Nomina Recibos": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                    "Pensionados": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                    "Negocio SAT": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                    "Sin Comprobantes": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                    "Guardia de Seguridad": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                },
                "selection_catalog": {
                    "Nomina Tarjeta": {
                        "label": "Nomina Tarjeta",
                        "aliases": ["nomina tarjeta"],
                        "field_updates": {"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
                    },
                    "Nomina Recibos": {
                        "label": "Nomina Recibos",
                        "aliases": ["nomina recibos"],
                        "field_updates": {"CREDITO": "Nomina Recibos", "ENGANCHE": "15%"},
                    },
                    "Pensionados": {
                        "label": "Pensionados",
                        "aliases": ["pensionado", "10%"],
                        "field_updates": {"CREDITO": "Pensionados", "ENGANCHE": "10%"},
                    },
                    "Negocio SAT": {
                        "label": "Negocio SAT",
                        "aliases": ["negocio sat"],
                        "field_updates": {"CREDITO": "Negocio SAT", "ENGANCHE": "15%"},
                    },
                    "Sin Comprobantes": {
                        "label": "Sin Comprobantes",
                        "aliases": ["sin comprobantes", "por fuera"],
                        "field_updates": {"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
                    },
                    "Guardia de Seguridad": {
                        "label": "Guardia de Seguridad",
                        "aliases": ["guardia", "guardia de seguridad"],
                        "field_updates": {"CREDITO": "Guardia de Seguridad", "ENGANCHE": "30%"},
                    },
                },
                "documents_catalog": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
                ],
                "stages": [
                    {
                        "id": "nuevos",
                        "label": "Nuevos",
                        "behavior_mode": "PLAN",
                        "actions_allowed": ["greet", "ask_field", "ask_clarification", "quote", "classify_document", "search_catalog"],
                    },
                    {
                        "id": "doc_incompleta",
                        "label": "Doc Incompleta",
                        "behavior_mode": "DOC",
                        "actions_allowed": ["classify_document", "ask_clarification", "quote"],
                    }
                ],
            },
        )
    )
    session.add(
        Customer(
            id=customer_id,
            tenant_id=tenant_id,
            phone_e164=phone_e164,
            name="Cliente Primary",
            attrs=attrs,
            tags=list(attrs.keys()),
            status="active",
            stage="nuevos",
            last_activity_at=created_at,
            ai_summary=ai_summary,
        )
    )
    await session.flush()
    session.add(
        Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel="whatsapp_meta",
            status="active",
            current_stage="nuevos",
            last_activity_at=created_at,
        )
    )
    session.add(
        ConversationStateRow(
            conversation_id=conversation_id,
            extracted_data=extracted_data or {},
            stage_entered_at=created_at,
            followups_sent_count=0,
            total_cost_usd=Decimal("0"),
            bot_paused=False,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_advisor_brain_output_contains_structured_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_payload = _brain_input(
        user_message="Quiero ver la adventure",
        contact_fields={
            "CREDITO": "Pensionados",
            "ENGANCHE": "10%",
            "ANTIGUEDAD_LABORAL": "2 anos",
        },
    )
    llm_payload = _brain_output(
        next_human_step="resolve_model",
        natural_response="Va, te ayudo con ese modelo.",
    ).model_dump(mode="json", exclude_none=True, exclude={"plan"})
    result = await _run_brain_with_payload(
        monkeypatch,
        input_payload=input_payload,
        llm_payload=llm_payload,
    )

    assert result.output is not None
    assert result.output.plan is not None
    assert result.output.plan.understanding.customer_message_summary
    assert result.output.plan.proposed_final_action == "search_catalog"
    assert isinstance(result.output.plan.proposed_final_action_payload, dict)
    assert result.output.plan.customer_response_goal


@pytest.mark.asyncio
async def test_runner_prefers_valid_agent_brain_plan_over_sales_policy() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={},
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_seniority",
                    detected_intent="collect_seniority",
                    natural_response="Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual.",
                    plan=_brain_plan(
                        proposed_final_action="ask_seniority",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "ask_employment_seniority",
                            "field_name": "ANTIGUEDAD_LABORAL",
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["agent_brain_plan_present"] is True
        assert trace.state_after["agent_brain_plan_valid"] is True
        assert trace.state_after["final_action_source"] == "advisor_brain"
        assert trace.state_after["final_action"] == "ask_seniority"
        assert trace.state_after["legacy_sales_policy_suppressed_by_advisor_brain"] is True
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_sales_policy_cannot_override_valid_brain_plan_without_guardrail_reason() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_seniority",
                    detected_intent="collect_seniority",
                    natural_response="Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual.",
                    plan=_brain_plan(
                        proposed_final_action="ask_seniority",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "ask_employment_seniority",
                            "field_name": "ANTIGUEDAD_LABORAL",
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["policy_overrode_agent_brain"] is False
        assert trace.state_after["policy_override_reason"] is None
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_guardrail_can_override_brain_documents_before_quote() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={},
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_first_missing_document",
                    detected_intent="document_received",
                    natural_response="Mandame tu INE por ambos lados para avanzar.",
                    plan=_brain_plan(
                        proposed_final_action="classify_document",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "ask_first_missing_document",
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Que sigue",
        )

        assert trace.state_after["agent_brain_plan_valid"] is True
        assert trace.state_after["policy_overrode_agent_brain"] is True
        assert trace.state_after["policy_override_reason"] == "documents_before_valid_quote"
        assert trace.state_after["final_action"] != "classify_document"
        assert trace.state_after["advisor_brain_primary_used"] is False
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_invalid_brain_plan_falls_back_to_legacy_runner() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        invalid_plan_output = _brain_output(
            next_human_step="ask_seniority",
            detected_intent="collect_seniority",
            natural_response="Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual.",
        ).model_copy(
            update={
                "plan": _brain_plan(
                    proposed_final_action="ask_seniority",
                    proposed_final_action_payload={},
                ).model_copy(
                    update={"proposed_final_action_payload": "not-a-dict"}
                )
            }
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=invalid_plan_output,
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["agent_brain_plan_present"] is True
        assert trace.state_after["agent_brain_plan_valid"] is False
        assert trace.state_after["agent_brain_plan_rejected_reason"] == "invalid_proposed_final_action_payload"
        assert trace.state_after["advisor_brain_primary_used"] is False
        assert trace.state_after["final_action_source"] != "advisor_brain"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_agent_brain_plan_is_visible_in_turntrace() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="resolve_model",
                    natural_response="Ya tengo tu perfil. Ahora dime que modelo te interesa.",
                    plan=_brain_plan(
                        proposed_final_action="search_catalog",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "resolve_model",
                            "query": "Adventure",
                        },
                        proposed_state_updates={"CREDITO": "Pensionados"},
                        tool_plan=[
                            {
                                "tool": "catalog.resolve_model",
                                "input": {"query": "Adventure"},
                                "required": True,
                                "reason": "Resolver el modelo pedido por el cliente.",
                            }
                        ],
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Quiero la adventure",
        )

        assert trace.state_after["agent_brain_plan_present"] is True
        assert trace.state_after["agent_brain_plan_valid"] is True
        assert trace.state_after["agent_brain_proposed_final_action"] == "search_catalog"
        assert trace.state_after["agent_brain_proposed_state_updates"]["CREDITO"] == "Pensionados"
        decision_layer = trace.state_after["runner_layers"]["decision"]
        assert decision_layer["agent_brain_plan_present"] is True
        assert decision_layer["agent_brain_plan_valid"] is True
        assert decision_layer["agent_brain_proposed_final_action"] == "search_catalog"
        assert decision_layer["agent_brain_tool_plan"][0]["tool"] == "catalog.resolve_model"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_agent_brain_plan_preserves_multi_intent_faq_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atendia.runner.sales_advisor_decision_policy import SalesAdvisorDecisionPolicy

    async def _fake_decide(self, input):
        del self, input
        return SalesAdvisorDecision(
            commercial_intent="buro",
            next_action="answer_faq_and_resume",
            runtime_action="lookup_faq",
            confidence=0.9,
            tool_payload={
                "status": "ok",
                "request_type": "faq_answer",
                "source_topic": "buro",
                "answer": "Si, revisamos buro.",
                "answers": [{"topic": "buro", "answer": "Si, revisamos buro."}],
                "answered_intents": ["buro"],
            },
            should_override_runtime_action=True,
        )

    monkeypatch.setattr(SalesAdvisorDecisionPolicy, "decide", _fake_decide)

    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="answer_and_resume_flow",
                    detected_intent="multi_intent_faq",
                    natural_response="Te respondo eso y luego seguimos con el siguiente paso util.",
                    plan=_brain_plan(
                        proposed_final_action="lookup_faq",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "faq_answer",
                            "source_topic": "buro",
                            "answer": "Liquidacion: si puedes liquidar antes.\nBuro: si se revisa.\nUbicacion: estamos en Monterrey.",
                            "answers": [
                                {"topic": "liquidacion", "answer": "Si puedes liquidar antes."},
                                {"topic": "buro", "answer": "Si se revisa buro."},
                                {"topic": "ubicacion", "answer": "Estamos en Monterrey."},
                            ],
                            "answered_intents": ["liquidacion", "buro", "ubicacion"],
                            "resume_pending_action": {"type": "ask_field", "field": "ANTIGUEDAD_LABORAL"},
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="puedo liquidar antes? checan buro? donde estan?",
        )

        assert trace.state_after["final_action"] == "lookup_faq"
        assert trace.state_after["final_action_payload"]["answered_intents"] == [
            "liquidacion",
            "buro",
            "ubicacion",
        ]
        assert trace.state_after["policy_overrode_agent_brain"] is False
        assert (
            trace.state_after["policy_override_reason"]
            == "policy_single_faq_cannot_override_brain_multi_intent"
        )
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_policy_soft_close_cannot_override_valid_brain_active_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atendia.runner.sales_advisor_decision_policy import SalesAdvisorDecisionPolicy

    async def _fake_decide(self, input):
        del self, input
        return SalesAdvisorDecision(
            commercial_intent="soft_close",
            next_action="soft_close",
            runtime_action="soft_close",
            confidence=0.9,
            tool_payload={"status": "ok", "request_type": "soft_close_candidate"},
            should_override_runtime_action=True,
        )

    monkeypatch.setattr(SalesAdvisorDecisionPolicy, "decide", _fake_decide)

    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_seniority",
                    detected_intent="collect_seniority",
                    natural_response="Antes de cotizar, dime cuanto tiempo llevas en tu empleo actual.",
                    plan=_brain_plan(
                        proposed_final_action="ask_seniority",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "ask_employment_seniority",
                            "field_name": "ANTIGUEDAD_LABORAL",
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="ok",
        )

        assert trace.state_after["final_action"] == "ask_seniority"
        assert trace.state_after["policy_overrode_agent_brain"] is False
        assert (
            trace.state_after["policy_override_reason"]
            == "policy_soft_close_cannot_override_valid_brain_active_intent"
        )
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_policy_browse_cannot_override_valid_brain_resolved_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atendia.runner.sales_advisor_decision_policy import SalesAdvisorDecisionPolicy

    async def _fake_decide(self, input):
        del self, input
        return SalesAdvisorDecision(
            commercial_intent="catalog_browse",
            next_action="catalog_browse",
            runtime_action="search_catalog",
            confidence=0.9,
            tool_payload={
                "status": "ok",
                "request_type": "catalog_browse",
                "query": "adventure",
            },
            should_override_runtime_action=True,
        )

    monkeypatch.setattr(SalesAdvisorDecisionPolicy, "decide", _fake_decide)

    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={
                "CREDITO": {"value": "Sin Comprobantes", "confidence": 1.0, "source_turn": 1},
                "ENGANCHE": {"value": "20%", "confidence": 1.0, "source_turn": 1},
                "FILTRO": {"value": True, "confidence": 1.0, "source_turn": 1},
                "MOTO": {"value": "Adventure Elite 150 CC", "confidence": 1.0, "source_turn": 1},
            },
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="quote",
                    detected_intent="model_change",
                    natural_response="Va, te recalculo la cotizacion con el modelo correcto.",
                    plan=_brain_plan(
                        proposed_final_action="quote",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "quote_refresh",
                        },
                        tool_plan=[
                            {
                                "tool": "catalog.resolve_model",
                                "input": {"query": "Adventure Elite 150 CC"},
                                "required": True,
                                "reason": "Confirmar modelo antes de recotizar.",
                            }
                        ],
                        proposed_state_updates={"MOTO": "Adventure Elite 150 CC"},
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="mejor la adventure",
        )

        assert trace.state_after["final_action"] == "quote"
        assert trace.state_after["final_action_source"] == "advisor_brain"
        assert trace.state_after["legacy_sales_policy_suppressed_by_advisor_brain"] is True
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_primary_brain_non_quote_plan_cannot_replace_ready_runner_requote() -> None:
    result = await _apply_advisor_brain_primary_response(
        session=SimpleNamespace(),
        tenant_id=uuid4(),
        customer_id=None,
        inbound=Message(
            id=str(uuid4()),
            conversation_id=str(uuid4()),
            tenant_id=str(uuid4()),
            direction=MessageDirection.INBOUND,
            text="la primera",
            metadata={},
            sent_at=datetime.now(UTC),
        ),
        turn_number=6,
        pipeline=SimpleNamespace(),
        history=[],
        agent_collection_ids=[],
        tool_dispatch=SimpleNamespace(),
        brain_input=SimpleNamespace(contact_fields={}),
        brain_result=AdvisorBrainResult(
            output=_brain_output(
                next_human_step="resolve_model",
                detected_intent="resolve_model",
                natural_response="Voy a buscarte otra opcion.",
                plan=_brain_plan(
                    proposed_final_action="search_catalog",
                    proposed_final_action_payload={
                        "status": "ok",
                        "request_type": "catalog_browse",
                    },
                ),
            ),
            llm_error=None,
            validation_error=None,
            guardrail_blocked=False,
            guardrail_reason=None,
            fallback_used=False,
            final_response_source="advisor_brain",
        ),
        current_runner_action="quote",
        current_runner_action_payload={
            "status": "ok",
            "name": "Alien R 175 CC",
            "requested_plan_code": "20%",
        },
        merged_extracted={
            "MOTO": {"value": "Alien R 175 CC"},
            "CREDITO": {"value": "Sin Comprobantes"},
            "ENGANCHE": {"value": "20%"},
        },
        state_obj=SimpleNamespace(extracted_data={}),
    )

    assert result["used"] is False
    assert result["fallback_to_runner"] is True
    assert result["fallback_reason"] == "runner_quote_preferred_over_non_quote_agent_plan"
    assert result["policy_override_reason"] == "runner_quote_preferred_over_non_quote_agent_plan"


@pytest.mark.asyncio
async def test_advisor_brain_primary_direct_is_wrapped_in_response_frame() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    final_message = "Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual."
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={},
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="ask_seniority",
                    detected_intent="collect_seniority",
                    natural_response=final_message,
                    plan=_brain_plan(
                        proposed_final_action="ask_credit_context",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "ask_income_type",
                            "field_name": "CREDITO",
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["response_frame_present"] is True
        assert trace.state_after["composer_output_source"] == "advisor_brain_primary_direct_wrapped"
        assert trace.state_after["fallback_preserved_response_frame"] is True
        assert trace.state_after["response_frame"]["validated_answers"]["wrapped_visible_answer"]["text"] == (
            final_message
        )
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_brain_final_message_not_sent_without_response_frame() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    final_message = "Claro, te ayudo. Dime que modelo te interesa."
    try:
        await _seed_primary_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
            phone_e164="+5215550001111",
            attrs={"TEST_CLIENT": True},
            advisor_brain_config={
                "enabled": True,
                "mode": "primary",
                "canary": True,
                "allowed_tenant_ids": [str(tenant_id)],
                "allowed_contact_ids": [str(customer_id)],
                "allowed_phone_numbers": ["+5215550001111"],
            },
            extracted_data={},
        )
        brain = _FixedBrain(
            AdvisorBrainResult(
                output=_brain_output(
                    next_human_step="resolve_model",
                    detected_intent="resolve_model",
                    natural_response=final_message,
                    plan=_brain_plan(
                        proposed_final_action="search_catalog",
                        proposed_final_action_payload={
                            "status": "ok",
                            "request_type": "catalog_browse",
                        },
                    ),
                ),
                llm_error=None,
                validation_error=None,
                guardrail_blocked=False,
                guardrail_reason=None,
                fallback_used=False,
                final_response_source="advisor_brain",
            )
        )
        runner = ConversationRunner(session, _StubNLU(), _StubComposer(), advisor_brain=brain)
        trace = await _run_turn(
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            sent_at=started_at,
            text="Hola quiero una moto a credito",
        )

        assert trace.state_after["response_frame_present"] is True
        assert trace.state_after["response_frame_valid"] is True
        assert trace.state_after["composer_output_source"] != "advisor_brain_primary_direct"
        assert trace.state_after["response_frame"]["trace"]["response_frame_reason"] == (
            "wrapped_customer_visible_answer"
        )
    finally:
        await session.rollback()
        await session.close()

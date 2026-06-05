from __future__ import annotations

import json
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorBrainToolRequest,
    ContextBuilder,
    MandatoryToolGuard,
    ToolExecutionResult,
    TurnInput,
    TurnOutput,
)
from atendia.agent_runtime.schemas import TenantRuntimeConfigContext, TurnContext
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _decision(response_plan: str = "Responder con datos validados.") -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Cliente pide un dato operativo.",
        customer_goal="answer",
        conversation_goals=["answer"],
        known_facts={},
        missing_facts=[],
        next_best_action="answer",
        proposed_state_changes=[],
        response_plan=response_plan,
        confidence=0.9,
    )


def _context_from_contract(raw: dict, tenant_id: str) -> TurnContext:
    result = load_tenant_domain_contract(raw, tenant_id=tenant_id, agent_id=raw.get("agent_id"))
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id="conversation-1",
        inbound_text="Hola",
        tenant_config=config,
    )


def test_dinamo_fixture_loads_vehicle_credit_sales() -> None:
    raw = _fixture("vehicle_credit_sales.json")

    result = load_tenant_domain_contract(
        raw,
        tenant_id="tenant_dinamo_fixture",
        agent_id="agent_francisco_fixture",
    )

    assert result.safe_mode is False
    assert result.contract.domain == "vehicle_credit_sales"
    assert result.contract.fields[0].key == "product_selection"
    assert {tool.tool_id for tool in result.contract.tools} == {
        "catalog.search",
        "quote.resolve",
        "requirements.lookup",
        "faq.lookup",
        "document.check",
    }


def test_non_dinamo_fixture_loads_appointment_services_without_vehicle_fields() -> None:
    raw = _fixture("appointment_services.json")

    result = load_tenant_domain_contract(
        raw,
        tenant_id="tenant_barber_fixture",
        agent_id="agent_barber_fixture",
    )
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)

    assert result.safe_mode is False
    assert config.domain == "appointment_services"
    assert set(config.field_metadata) == {
        "service_selection",
        "appointment_time",
        "booking_status",
    }
    assert "product_selection" not in config.field_metadata
    assert "plan_selection" not in config.field_metadata
    assert "quote_snapshot_id" not in config.field_metadata


def test_invalid_config_falls_back_to_safe_mode() -> None:
    result = load_tenant_domain_contract(
        {
            "contract_version": "2.0",
            "tenant_id": "tenant-b",
            "domain": "vehicle_credit_sales",
        },
        tenant_id="tenant-b",
    )
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)

    assert result.safe_mode is True
    assert result.reason == "invalid_contract"
    assert config.domain == "generic_lead_qualification"
    assert config.safe_mode is True
    assert config.tenant_domain_contract["safe_mode"] is True
    assert config.guard_metadata == {
        "mandatory_tool_guard": {"guard_id": "mandatory_tool_guard"},
        "final_copy_guard": {"guard_id": "final_copy_guard"},
    }


def test_tenant_id_mismatch_falls_back_to_safe_mode() -> None:
    raw = _fixture("vehicle_credit_sales.json")

    result = load_tenant_domain_contract(raw, tenant_id="tenant-b")

    assert result.safe_mode is True
    assert result.reason == "tenant_id_mismatch"
    assert result.contract.tenant_id == "tenant-b"


@pytest.mark.asyncio
async def test_context_builder_exposes_tenant_domain_metadata_from_fixture() -> None:
    raw = _fixture("vehicle_credit_sales.json")

    context = await ContextBuilder().build(
        TurnInput(
            tenant_id="tenant_dinamo_fixture",
            conversation_id="conversation-1",
            inbound_text="Hola",
            metadata={"tenant_domain_contract": raw, "agent_id": "agent_francisco_fixture"},
        )
    )

    assert context.tenant_config.domain == "vehicle_credit_sales"
    assert context.tenant_config.safe_mode is False
    assert context.tenant_config.field_metadata["product_selection"]["domain_role"] == "selection"
    assert context.tenant_config.tool_metadata["quote.resolve"]["topic"] == "offer_or_quote"
    assert context.metadata["tenant_domain_contract"] == {
        "version": "1.0",
        "domain": "vehicle_credit_sales",
        "safe_mode": False,
    }
    assert context.metadata["field_metadata_loaded"] is True
    assert context.metadata["tool_metadata_loaded"] is True
    assert context.metadata["pipeline_metadata_loaded"] is True
    assert context.metadata["guard_metadata_loaded"] is True


@pytest.mark.asyncio
async def test_context_builder_safe_mode_when_contract_missing() -> None:
    context = await ContextBuilder().build(
        TurnInput(
            tenant_id="tenant-b",
            conversation_id="conversation-1",
            inbound_text="Hola",
        )
    )

    assert context.tenant_config.safe_mode is True
    assert context.tenant_config.domain == "generic_lead_qualification"
    assert context.metadata["tenant_domain_contract"]["safe_mode"] is True
    assert context.metadata["tenant_domain_contract"]["reason"] == "missing_contract"


def test_mandatory_tool_guard_uses_tenant_declared_appointment_tools() -> None:
    context = _context_from_contract(
        _fixture("appointment_services.json"),
        "tenant_barber_fixture",
    )

    result = MandatoryToolGuard().apply(
        context=context,
        decision=_decision("Confirmar cita con disponibilidad validada."),
        tool_results=[],
        output=TurnOutput(
            final_message="Tu cita queda confirmada para manana a las 5.",
            confidence=0.9,
        ),
    )

    assert "confirmada" not in result.output.final_message
    decisions = result.output.trace_metadata["mandatory_tool_decisions"]
    availability = next(item for item in decisions if item["tool_id"] == "availability.check")
    booking = next(item for item in decisions if item["tool_id"] == "booking.create")
    assert availability["status"] == "missing"
    assert booking["status"] == "missing"


def test_tenant_declared_appointment_tools_satisfy_booking_guard() -> None:
    context = _context_from_contract(
        _fixture("appointment_services.json"),
        "tenant_barber_fixture",
    )

    result = MandatoryToolGuard().apply(
        context=context,
        decision=_decision("Confirmar cita con disponibilidad validada."),
        tool_results=[
            ToolExecutionResult(
                tool_name="availability.check",
                status="succeeded",
                data={"tenant_id": "tenant_barber_fixture", "slots": ["17:00"]},
            ),
            ToolExecutionResult(
                tool_name="booking.create",
                status="succeeded",
                data={"tenant_id": "tenant_barber_fixture", "booking_id": "booking-1"},
            ),
        ],
        output=TurnOutput(
            final_message="Tu cita queda confirmada para manana a las 5.",
            confidence=0.9,
        ),
    )

    assert result.output.final_message == "Tu cita queda confirmada para manana a las 5."
    decisions = result.output.trace_metadata["mandatory_tool_decisions"]
    availability = next(item for item in decisions if item["tool_id"] == "availability.check")
    booking = next(item for item in decisions if item["tool_id"] == "booking.create")
    assert availability["status"] == "executed"
    assert booking["status"] == "executed"


def test_mandatory_tool_guard_uses_tenant_declared_aliases() -> None:
    context = _context_from_contract(
        _fixture("appointment_services.json"),
        "tenant_barber_fixture",
    )

    evaluation = MandatoryToolGuard().evaluate(
        context=context,
        decision=AdvisorBrainDecision(
            understanding="Cliente pide reservar.",
            customer_goal="booking",
            conversation_goals=["booking"],
            known_facts={},
            missing_facts=[],
            next_best_action="book",
            proposed_state_changes=[],
            response_plan="Crear reserva con tool.",
            confidence=0.9,
            required_tools=[
                AdvisorBrainToolRequest(
                    name="booking",
                    payload={},
                    reason="Tenant alias for booking.create.",
                    required=True,
                )
            ],
        ),
        tool_results=[
            ToolExecutionResult(
                tool_name="booking.create",
                status="succeeded",
                data={"tenant_id": "tenant_barber_fixture", "booking_id": "booking-1"},
            )
        ],
    )

    booking_decision = next(
        decision for decision in evaluation.decisions if decision.tool_id == "booking.create"
    )
    assert booking_decision.status == "executed"

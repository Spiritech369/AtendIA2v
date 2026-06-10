from __future__ import annotations

import json
from pathlib import Path

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainToolRequest,
    CustomerContext,
    MessageContext,
    TenantRuntimeConfigContext,
    TurnContext,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)

TENANT_ID = "5528e854-f446-46e8-bac0-bac28a8492fe"
AGENT_ID = "d447fffe-ab1e-4861-8385-3b26d3b4aebc"
CONTRACT_PATH = Path("docs/tenant_sources/dinamo/dinamo_runtime_contract.json")
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_business_activity_signal_requires_tax_status_clarification() -> None:
    result = await _resolve_income("Tengo negocio", candidate="negocio_sat")

    assert result.status == "succeeded"
    assert result.data["needs_clarification"] is True
    assert result.data["pending_slot"] == "business_tax_status"
    assert result.data["field_updates"] == []
    assert result.data["clarification"] == {
        "code": "income_business_tax_status_required",
        "pending_slot": "business_tax_status",
        "source": "tenant_income_resolution_policy",
    }


@pytest.mark.asyncio
async def test_no_sat_resolves_sin_comprobantes_from_tenant_policy() -> None:
    result = await _resolve_income("No tengo SAT", candidate="sin_comprobantes")

    assert result.status == "succeeded"
    assert result.data["plan_id"] == "sin_comprobantes_20"
    assert result.data["plan_credito"] == "20%"
    assert result.data["down_payment_percent"] == 20
    assert {item["key"] for item in result.data["field_updates"]} == {
        "plan_selection",
        "down_payment_percent",
    }


@pytest.mark.asyncio
async def test_no_sat_evidence_overrides_wrong_semantic_candidate() -> None:
    result = await _resolve_income("No tengo SAT", candidate="negocio_sat")

    assert result.status == "succeeded"
    assert result.data["plan_id"] == "sin_comprobantes_20"
    assert result.data["plan_credito"] == "20%"
    assert result.data["down_payment_percent"] == 20


async def _resolve_income(inbound: str, *, candidate: str) -> object:
    results = await TenantKnowledgeToolLayer().execute(
        context=_context(inbound),
        decision=AdvisorBrainDecision(
            understanding="Cliente responde tipo de ingreso.",
            customer_goal="credit_plan",
            next_best_action="validate_income",
            response_plan="Resolver ingreso contra contrato tenant.",
            confidence=0.9,
            required_tools=[
                AdvisorBrainToolRequest(
                    name="credit_plan.resolve",
                    payload={
                        "raw_answer": inbound,
                        "income_candidate": candidate,
                        "evidence": inbound,
                    },
                    reason="Validar plan con tenant policy.",
                    evidence=[inbound],
                    required=True,
                )
            ],
        ),
    )
    assert len(results) == 1
    return results[0]


def _context(inbound: str) -> TurnContext:
    contract = json.loads((REPO_ROOT / CONTRACT_PATH).read_text(encoding="utf-8"))
    result = load_tenant_domain_contract(contract, tenant_id=TENANT_ID, agent_id=AGENT_ID)
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)
    config = config.model_copy(
        update={
            "knowledge_sources": [
                source["path"]
                for source in contract["knowledge_os"]["sources"].values()
                if source.get("path", "").endswith(".json")
            ],
            "metadata": {
                **config.metadata,
                "knowledge_os": contract["knowledge_os"],
            },
        }
    )
    return TurnContext(
        tenant_id=TENANT_ID,
        conversation_id="dinamo-income-policy-test",
        inbound_text=inbound,
        customer=CustomerContext(id="contact-test", phone_e164="+5218128889241"),
        messages=[MessageContext(role="customer", text=inbound)],
        tenant_config=config,
        metadata={"agent_id": AGENT_ID, "no_send": True},
    )

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from atendia.agent_runtime.knowledge_tool_layer import TenantKnowledgeToolLayer
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainToolRequest,
    ConversationMemoryContext,
    CustomerContext,
    TenantRuntimeConfigContext,
    TurnContext,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)

REPO_ROOT = next(
    (
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "docs" / "tenant_sources" / "dinamo").exists()
    ),
    Path(__file__).resolve().parents[3],
)
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"
DINAMO_TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DINAMO_AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")
TENANT_SOURCES = [
    Path("docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json"),
    Path("docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json"),
    Path("docs/tenant_sources/dinamo/FAQ_DINAMO.json"),
]


def test_container_runtime_sources_available() -> None:
    compose_path = REPO_ROOT / "docker-compose.yml"

    if compose_path.exists():
        compose = compose_path.read_text(encoding="utf-8")
        assert "./docs/tenant_sources:/app/docs/tenant_sources:ro" in compose
    for source in TENANT_SOURCES:
        path = REPO_ROOT / source
        assert path.exists(), f"missing tenant source: {source}"
        assert path.stat().st_size > 0, f"empty tenant source: {source}"


@pytest.mark.asyncio
async def test_live_candidate_uses_same_sources_as_no_send() -> None:
    no_send = _context(mode="no_send")
    live_candidate = _context(mode="live_candidate")
    layer = TenantKnowledgeToolLayer()
    decision = _income_decision()

    no_send_results = await layer.execute(context=no_send, decision=decision)
    live_results = await layer.execute(context=live_candidate, decision=decision)

    assert [result.status for result in no_send_results] == ["succeeded"]
    assert [result.status for result in live_results] == ["succeeded"]
    assert no_send_results[0].data["source_path"] == live_results[0].data["source_path"]
    assert no_send_results[0].data["plan_id"] == "nomina_tarjeta_10"


@pytest.mark.asyncio
async def test_required_tool_source_missing_blocks_smoke_readiness() -> None:
    context = _context(
        mode="live_candidate",
        knowledge_sources=[],
        include_metadata_sources=False,
    )
    result = (
        await TenantKnowledgeToolLayer().execute(
            context=context,
            decision=_income_decision(),
        )
    )[0]

    assert result.tool_name == "credit_plan.resolve"
    assert result.status == "skipped"
    assert result.data["reason"] == "requirements source and explicit income signal required"


def _income_decision() -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Cliente responde ingreso despues de antiguedad.",
        customer_goal="answer_pending_slot",
        next_best_action="resolve_credit_plan",
        response_plan="Validar tipo de ingreso contra requisitos.",
        confidence=0.9,
        latest_customer_act="answer_to_pending_slot",
        answered_slot="income_type",
        required_tools=[
            AdvisorBrainToolRequest(
                name="credit_plan.resolve",
                payload={
                    "raw_answer": "Me pagan por transferencia",
                    "pending_slot": "income_type",
                    "last_bot_question": "Como recibes tus ingresos?",
                    "income_candidate": "nomina_tarjeta",
                    "evidence": "Me pagan por transferencia",
                },
            )
        ],
    )


def _context(
    *,
    mode: str,
    knowledge_sources: list[str] | None = None,
    include_metadata_sources: bool = True,
) -> TurnContext:
    config = TenantRuntimeConfigContext(
        knowledge_sources=knowledge_sources
        if knowledge_sources is not None
        else [str(source) for source in TENANT_SOURCES],
        metadata=(
            {
                "knowledge_os": {
                    "sources": {
                        "catalog": {"path": str(TENANT_SOURCES[0])},
                        "requirements": {"path": str(TENANT_SOURCES[1])},
                        "faq": {"path": str(TENANT_SOURCES[2])},
                    },
                    "mode": "tenant_structured_sources",
                }
            }
            if include_metadata_sources
            else {}
        ),
    )
    contract = json.loads(
        (FIXTURE_DIR / "dinamo_motos_nl_shadow.json").read_text(encoding="utf-8")
    )
    result = load_tenant_domain_contract(
        contract,
        tenant_id=str(DINAMO_TENANT_ID),
        agent_id=str(DINAMO_AGENT_ID),
    )
    config = apply_tenant_domain_contract(config, result)
    return TurnContext(
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id=f"container-sources-{mode}",
        inbound_text="Me pagan por transferencia",
        customer=CustomerContext(
            id="contact-container-sources",
            phone_e164="+5218128889241",
            attrs={"employment_seniority": 24},
        ),
        memory=ConversationMemoryContext(
            salient_facts={"employment_seniority": 24},
            metadata={"pending_slot": "income_type"},
            last_pending_question="Como recibes tus ingresos?",
        ),
        tenant_config=config,
        metadata={"send_mode": mode},
    )

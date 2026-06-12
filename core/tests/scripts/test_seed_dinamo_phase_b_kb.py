from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from atendia.agent_runtime.respond_style_real_facts_executor import RealFactsToolExecutor
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    LLMToolCallProposal,
)
from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import AgentDeployment, AgentVersion
from atendia.scripts import seed_dinamo_phase_b_kb as phase_b
from atendia.scripts.seed_dinamo_v1 import AGENT_NAME


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeResult:
    def __init__(self, *, scalar=None, values=None):
        self._scalar = scalar
        self._values = values or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.flush_count = 0

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = uuid4()
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


def test_load_source_specs_uses_runtime_contract_source_ids() -> None:
    specs = phase_b.load_source_specs()

    by_key = {spec.key: spec for spec in specs}
    assert set(by_key) == {"catalog", "requirements", "faq"}
    assert by_key["catalog"].source_id == "dinamo_catalogo_junio_2026"
    assert by_key["requirements"].source_id == "dinamo_requisitos_junio_2026"
    assert by_key["faq"].source_id == "dinamo_faq_junio_2026"
    assert by_key["catalog"].required is True
    assert by_key["faq"].priority < by_key["catalog"].priority


def test_load_phase_b_payload_matches_approved_gate_counts() -> None:
    specs, meta_by_key, models, plans, faqs = phase_b.load_phase_b_payload()

    assert len(specs) == 3
    assert len(models) == 34
    assert len(plans) == 6
    assert len(faqs) == 26
    assert len(meta_by_key["catalog"]["hash"]) == 64
    assert meta_by_key["catalog"]["runtime_status"] == "approved"
    assert meta_by_key["catalog"]["json_wins_over_docx"] is True


def test_catalog_models_are_normalized_for_quote_and_catalog_tools() -> None:
    _specs, meta_by_key, models, _plans, _faqs = phase_b.load_phase_b_payload()
    adventure = next(item for item in models if item["sku"] == "adventure_elite_150_cc")

    assert adventure["name"] == "Adventure Elite 150 CC"
    assert adventure["attrs"]["catalog_source"]["source_id"] == meta_by_key["catalog"]["source_id"]
    assert adventure["attrs"]["list_price_mxn"] == "31395"
    assert adventure["attrs"]["cash_price_mxn"] == "29900"
    assert set(adventure["attrs"]["payment_options"]) == {"10%", "15%", "20%", "30%"}
    assert adventure["attrs"]["payment_options"]["10%"]["enganche_mxn"] == 3140
    assert adventure["runtime_fact"]["planes_credito"]["10%"]["pago_quincenal_mxn"] == 1247


def test_requirement_plans_are_normalized_for_real_facts_executor() -> None:
    _specs, _meta_by_key, _models, plans, _faqs = phase_b.load_phase_b_payload()
    plan = next(item for item in plans if item["id"] == "nomina_tarjeta_10")

    assert plan["runtime_fact"]["tipo_credito"] == "Nómina Tarjeta"
    assert plan["runtime_fact"]["plan_credito"] == "10%"
    assert "me depositan nómina" in plan["runtime_fact"]["aliases_usuario"]
    assert "INE vigente por ambos lados" in plan["runtime_fact"]["texto_retrieval"]


def test_tool_policy_bindings_configure_real_sources_and_dry_facts() -> None:
    _specs, meta_by_key, models, plans, _faqs = phase_b.load_phase_b_payload()
    bindings = phase_b.build_tool_policy_bindings(
        existing_bindings=[{"name": "quote.resolve", "required": True}],
        models=models,
        plans=plans,
        meta_by_key=meta_by_key,
    )

    by_name = {binding["name"]: binding for binding in bindings}
    assert by_name["catalog.search"]["real_source"] == "catalog_search"
    assert by_name["quote.resolve"]["real_source"] == "catalog_quote"
    assert by_name["requirements.lookup"]["real_source"] == "knowledge_plans"
    assert len(by_name["catalog.search"]["dry_facts"]["models"]) == 34
    assert len(by_name["requirements.lookup"]["dry_facts"]["requirement_plans"]) == 6
    assert by_name["quote.resolve"]["preconditions"] == []


def test_real_facts_executor_answers_phase_b_quote_and_requirements() -> None:
    _specs, meta_by_key, models, plans, _faqs = phase_b.load_phase_b_payload()
    bindings = phase_b.build_tool_policy_bindings(
        existing_bindings=[],
        models=models,
        plans=plans,
        meta_by_key=meta_by_key,
    )
    facts = {
        "models": [item["runtime_fact"] for item in models],
        "requirement_plans": [item["runtime_fact"] for item in plans],
    }
    executor = RealFactsToolExecutor(bindings, facts)
    context = AgentContextPackage(
        agent_identity={"contact_state": {"selected_model": "Adventure Elite 150 CC"}},
    )

    quote = executor.execute_tool(
        LLMToolCallProposal(
            tool_name="quote.resolve",
            arguments={"Moto": "Adventure Elite 150 CC"},
            reason="test",
            required=True,
        ),
        context,
    )
    requirements = executor.execute_tool(
        LLMToolCallProposal(
            tool_name="requirements.lookup",
            arguments={"income_type": "me depositan nómina"},
            reason="test",
            required=True,
        ),
        context,
    )

    assert quote.status == "succeeded"
    assert quote.facts["model"]["model_id"] == "adventure_elite_150_cc"
    assert quote.facts["planes_credito"]["10%"]["numero_quincenas"] == 72
    assert requirements.status == "succeeded"
    assert requirements.facts["matched"] is True
    assert requirements.facts["plans"][0]["plan_credito"] == "10%"


def test_phase_b_script_does_not_import_openai_or_external_clients() -> None:
    source = Path(phase_b.__file__).read_text(encoding="utf-8")

    lowered = source.casefold()
    assert "import openai" not in lowered
    assert "from openai" not in lowered
    assert "import requests" not in lowered
    assert "import httpx" not in lowered


async def test_seed_phase_b_dry_run_reports_gate_counts_without_db() -> None:
    result = await phase_b.seed_dinamo_phase_b_kb(
        FakeSession(),
        tenant_id=uuid4(),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.catalog_models == 34
    assert result.requirement_plans == 6
    assert result.faqs == 26
    assert result.tool_policy_action == "would_update"
    assert result.deployment_guard == "would_check_no_send"


async def test_seed_phase_b_full_path_uses_no_send_guard_and_creates_bindings() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version_id = uuid4()
    agent = Agent(tenant_id=tenant_id, id=agent_id, name=AGENT_NAME)
    version = AgentVersion(
        tenant_id=tenant_id,
        id=version_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        knowledge_policy={},
        tool_policy={"bindings": []},
        snapshot={"source": "dinamo_tenant_runtime_plan_v1"},
    )
    deployment = AgentDeployment(
        tenant_id=tenant_id,
        agent_id=agent_id,
        active_version_id=version_id,
        name="Dinamo V1 no-send",
        channel="test_lab",
        environment="no_send",
        send_scope="none",
        send_enabled=False,
        outbox_enabled=False,
        live_send_enabled=False,
        single_contact_smoke_enabled=False,
        actions_enabled=False,
        workflow_events_enabled=False,
        workflow_side_effects_enabled=False,
        canary_enabled=False,
        open_production_enabled=False,
    )
    session = FakeSession(
        FakeResult(scalar=agent),
        FakeResult(scalar=version),
        FakeResult(values=[deployment]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(scalar=None),
        FakeResult(values=[]),
        FakeResult(values=[]),
    )

    result = await phase_b.seed_dinamo_phase_b_kb(
        session,
        tenant_id=tenant_id,
        dry_run=False,
    )

    assert result.dry_run is False
    assert result.deployment_guard == "checked_1_deployments_no_send"
    assert result.created_sources == [
        "dinamo_catalogo_junio_2026",
        "dinamo_requisitos_junio_2026",
        "dinamo_faq_junio_2026",
    ]
    assert result.created_bindings == result.created_sources
    assert result.tool_policy_action == "updated"
    assert version.knowledge_policy["phase"] == "B"
    assert version.tool_policy["phase"] == "B"
    by_name = {binding["name"]: binding for binding in version.tool_policy["bindings"]}
    assert by_name["quote.resolve"]["real_source"] == "catalog_quote"
    assert len(result.created_catalog_items) == 34
    assert len(result.created_faqs) == 26
    assert session.results == []


async def test_no_send_guard_fails_closed_when_deployment_can_send() -> None:
    tenant_id = uuid4()
    version = AgentVersion(
        tenant_id=tenant_id,
        id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        status="draft",
    )
    unsafe = AgentDeployment(
        tenant_id=tenant_id,
        agent_id=version.agent_id,
        active_version_id=version.id,
        name="unsafe",
        channel="test_lab",
        environment="no_send",
        send_scope="all",
        send_enabled=True,
    )
    session = FakeSession(FakeResult(values=[unsafe]))

    with pytest.raises(RuntimeError, match="not no-send"):
        await phase_b._guard_no_send(session, tenant_id, version)


async def test_get_phase_a_version_requires_existing_phase_a_agent() -> None:
    session = FakeSession(FakeResult(scalar=None))

    with pytest.raises(RuntimeError, match="Phase A agent is missing"):
        await phase_b._get_phase_a_version(session, uuid4())


async def test_upsert_sources_updates_existing_source_metadata() -> None:
    tenant_id = uuid4()
    specs, meta_by_key, _models, _plans, _faqs = phase_b.load_phase_b_payload()
    catalog = next(spec for spec in specs if spec.key == "catalog")
    existing = KnowledgeSource(
        tenant_id=tenant_id,
        id=uuid4(),
        name="old",
        type="file",
        content_type="catalog",
        status="draft",
        priority=1,
        metadata_json={"source_id": catalog.source_id, "hash": "old"},
    )
    result = phase_b.PhaseBResult(tenant_id=str(tenant_id), dry_run=False)
    session = FakeSession(FakeResult(values=[existing]))

    sources = await phase_b._upsert_sources(
        session,
        tenant_id=tenant_id,
        specs=[catalog],
        meta_by_key=meta_by_key,
        result=result,
    )

    assert sources["catalog"] is existing
    assert existing.status == "active"
    assert existing.metadata_json["hash"] == meta_by_key["catalog"]["hash"]
    assert result.updated_sources == [catalog.source_id]

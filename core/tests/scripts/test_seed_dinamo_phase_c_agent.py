from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentKnowledgeSourceBinding,
    AgentToolBinding,
    AgentVersion,
)
from atendia.scripts import seed_dinamo_phase_c_agent as phase_c
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
        self.flush_count = 0

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    async def flush(self):
        self.flush_count += 1


def test_phase_c_instructions_keep_visible_identity_and_no_internal_leaks() -> None:
    instructions = phase_c.build_phase_c_instructions()
    blocks = phase_c.build_prompt_blocks()
    combined = "\n".join([instructions, *[block["text"] for block in blocks]]).casefold()

    assert "francisco esparza" in combined
    assert "te paso con" not in combined
    assert "frank" not in combined
    assert "nombres de herramientas" in combined
    assert "turnoutput.final_message" in combined
    assert "no prometas aprobacion" in combined


def test_phase_c_tool_policy_preserves_phase_b_real_sources_and_dry_facts() -> None:
    existing = {
        "bindings": [
            {
                "name": "quote.resolve",
                "real_source": "catalog_quote",
                "dry_facts": {"models": [{"model_id": "adventure_elite_150_cc"}]},
            }
        ]
    }

    policy = phase_c.build_phase_c_tool_policy(existing)
    quote = next(item for item in policy["bindings"] if item["name"] == "quote.resolve")

    assert policy["phase"] == "C"
    assert quote["real_source"] == "catalog_quote"
    assert quote["dry_facts"]["models"][0]["model_id"] == "adventure_elite_150_cc"
    assert quote["customer_visible_output_allowed"] is False
    assert set(policy["required_tools"]) == {
        "catalog.search",
        "quote.resolve",
        "requirements.lookup",
    }


def test_phase_c_payload_encodes_post_handoff_limited_mode() -> None:
    payload = phase_c.build_phase_c_payload()
    post_handoff = payload["action_policy"]["post_handoff_policy"]

    assert payload["snapshot"]["phase"] == "C"
    assert payload["safety_policy"]["openai_api_real"] is False
    assert post_handoff["enabled_when_field"] == "Handoff_Humano"
    assert post_handoff["mode"] == "limited"
    assert "quote.resolve" in post_handoff["blocked_capabilities"]
    assert "faq.lookup" in post_handoff["allowed_capabilities"]


async def test_seed_phase_c_dry_run_reports_no_send_and_openai_pending() -> None:
    result = await phase_c.seed_dinamo_phase_c_agent(
        FakeSession(),
        tenant_id=uuid4(),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.deployment_guard == "would_check_no_send"
    assert result.openai_api_real is False
    assert result.external_apis is False
    assert result.send == "no_send"
    assert result.gate_status == "phase_c_config_ready_openai_gate_pending"
    assert result.updated_tool_bindings == [
        "catalog.search",
        "quote.resolve",
        "requirements.lookup",
        "faq.lookup",
        "document.check",
        "expediente.evaluate",
        "handoff.request",
        "followup.schedule",
    ]


async def test_phase_c_no_send_guard_fails_closed_when_deployment_can_send() -> None:
    tenant_id = uuid4()
    version = AgentVersion(
        tenant_id=tenant_id,
        id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        status="draft",
    )
    deployment = AgentDeployment(
        tenant_id=tenant_id,
        agent_id=version.agent_id,
        active_version_id=version.id,
        name="unsafe",
        channel="test_lab",
        environment="no_send",
        send_scope="all",
        send_enabled=True,
    )

    with pytest.raises(RuntimeError, match="not no-send"):
        await phase_c._guard_no_send(
            FakeSession(FakeResult(values=[deployment])),
            tenant_id,
            version,
        )


async def test_phase_c_full_path_updates_agent_version_and_bindings() -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    version_id = uuid4()
    source_catalog = KnowledgeSource(
        tenant_id=tenant_id,
        id=uuid4(),
        name="Catalog",
        type="file",
        content_type="catalog",
        status="active",
        metadata_json={
            "source_id": "dinamo_catalogo_junio_2026",
            "runtime_status": "approved",
        },
    )
    source_requirements = KnowledgeSource(
        tenant_id=tenant_id,
        id=uuid4(),
        name="Requirements",
        type="file",
        content_type="document_rules",
        status="active",
        metadata_json={
            "source_id": "dinamo_requisitos_junio_2026",
            "runtime_status": "approved",
        },
    )
    source_faq = KnowledgeSource(
        tenant_id=tenant_id,
        id=uuid4(),
        name="FAQ",
        type="file",
        content_type="faq",
        status="active",
        metadata_json={"source_id": "dinamo_faq_junio_2026", "runtime_status": "approved"},
    )
    agent = Agent(tenant_id=tenant_id, id=agent_id, name=AGENT_NAME)
    version = AgentVersion(
        tenant_id=tenant_id,
        id=version_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        tool_policy={
            "bindings": [
                {
                    "name": "quote.resolve",
                    "real_source": "catalog_quote",
                    "dry_facts": {"models": [{"model_id": "adventure_elite_150_cc"}]},
                }
            ]
        },
        snapshot={"phase": "B"},
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
    tool_rows = [
        AgentToolBinding(
            tenant_id=tenant_id,
            agent_version_id=version_id,
            tool_name=tool_name,
            enabled=True,
            required=False,
            metadata_json={},
        )
        for tool_name in [*phase_c.REQUIRED_TOOLS, *phase_c.OPTIONAL_TOOLS]
    ]
    session = FakeSession(
        FakeResult(scalar=agent),
        FakeResult(scalar=version),
        FakeResult(values=[deployment]),
        FakeResult(values=[source_catalog, source_requirements, source_faq]),
        FakeResult(
            values=[
                AgentKnowledgeSourceBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version_id,
                    knowledge_source_id=source_catalog.id,
                    required=True,
                ),
                AgentKnowledgeSourceBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version_id,
                    knowledge_source_id=source_requirements.id,
                    required=True,
                ),
            ]
        ),
        FakeResult(values=tool_rows),
    )

    result = await phase_c.seed_dinamo_phase_c_agent(
        session,
        tenant_id=tenant_id,
        dry_run=False,
    )

    assert result.deployment_guard == "checked_1_deployments_no_send"
    assert result.required_sources_checked == list(phase_c.REQUIRED_SOURCE_IDS)
    assert result.optional_sources_checked == ["dinamo_faq_junio_2026"]
    assert agent.max_sentences == 2
    assert agent.no_emoji is True
    assert version.snapshot["phase"] == "C"
    assert version.tool_policy["phase"] == "C"
    quote = next(
        item for item in version.tool_policy["bindings"] if item["name"] == "quote.resolve"
    )
    assert quote["real_source"] == "catalog_quote"
    assert quote["dry_facts"]["models"][0]["model_id"] == "adventure_elite_150_cc"
    assert all(row.metadata_json["phase"] == "C" for row in tool_rows)
    assert session.results == []


def test_phase_c_script_does_not_import_external_clients() -> None:
    source = Path(phase_c.__file__).read_text(encoding="utf-8").casefold()

    assert "import openai" not in source
    assert "from openai" not in source
    assert "import requests" not in source
    assert "import httpx" not in source

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

from atendia.contact_memory.policy import policy_config_dict
from atendia.db.models.agent import Agent
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.product_agent import AgentVersion
from atendia.db.models.workflow import Workflow
from atendia.scripts import seed_dinamo_v1 as seed_module
from atendia.scripts.seed_dinamo_v1 import (
    FIELD_SPECS,
    HANDOFF_REASON_CHOICES,
    PLAN_CREDITO_CHOICES,
    PLAN_ENGANCHE_BY_PLAN,
    SEED_ID,
    SOURCE_VERSION_ID,
    TEMPLATE_SPECS,
    archive_field_options,
    build_agent_payload,
    build_field_options,
    build_pipeline_definition,
    build_tool_binding_specs,
    build_workflow_specs,
    canonical_field_keys,
    load_requirements,
    parse_docs_per_plan,
    preview_dinamo_v1_seed,
)

ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS_PATH = ROOT / "docs" / "tenant_sources" / "dinamo" / "Requisitos_Credito_Dinamo.json"


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

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

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

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_exc):
        return False


def _field(key: str):
    return next(spec for spec in FIELD_SPECS if spec.key == key)


def test_canonical_fields_include_v1_operator_and_admin_sets() -> None:
    keys = canonical_field_keys()

    assert {
        "Cumple_Antiguedad",
        "Plan_Credito",
        "Plan_Enganche",
        "Moto",
        "Docs_Checklist",
        "Cotizacion_Enviada",
        "Ultima_Cotizacion",
        "Handoff_Humano",
        "Motivo_Handoff",
        "Autorizado",
        "Solicitud_ID",
        "Followups_Enviados",
        "Proximo_Followup",
    } <= keys
    assert "plan_credito" not in keys
    assert "docs_ine" not in keys


def test_plan_credito_and_enganche_options_match_approved_business_rules() -> None:
    plan_options = build_field_options(_field("Plan_Credito"))
    enganche_options = build_field_options(_field("Plan_Enganche"))

    assert plan_options["choices"] == list(PLAN_CREDITO_CHOICES)
    assert enganche_options["choices"] == ["10%", "15%", "20%", "30%"]
    assert enganche_options["derivation"]["from_field"] == "Plan_Credito"
    assert enganche_options["derivation"]["map"] == PLAN_ENGANCHE_BY_PLAN
    assert PLAN_ENGANCHE_BY_PLAN["Sin Comprobantes"] == "20%"
    assert PLAN_ENGANCHE_BY_PLAN["Guardia de Seguridad"] == "30%"


def test_field_options_encode_visibility_aliases_source_and_contact_memory_policy() -> None:
    moto_options = build_field_options(_field("Moto"))
    source_options = build_field_options(_field("Source_Version_ID"))

    assert moto_options["source"] == SEED_ID
    assert moto_options["source_version_id"] == SOURCE_VERSION_ID
    assert "modelo_interes" in moto_options["aliases"]
    assert moto_options["tool_evidence_required"] == ["catalog.search", "quote.resolve"]
    assert source_options["visibility"] == "admin"
    assert source_options["admin_visible"] is True

    definition = CustomerFieldDefinition(
        tenant_id="00000000-0000-0000-0000-000000000001",
        key="Moto",
        label="Moto",
        field_type="text",
        field_options=moto_options,
    )
    policy = policy_config_dict(definition)
    assert policy["extractable_by_ai"] is True
    assert policy["evidence_required"] is True
    assert policy["write_policy"] == "ai_auto"


def test_system_and_human_only_fields_are_not_agent_writable() -> None:
    locked = {
        "Autorizado",
        "Plan_Enganche",
        "Docs_Checklist",
        "Doc_Incompletos",
        "Doc_Completos",
        "Cotizacion_Enviada",
        "Ultima_Cotizacion",
        "Transcripcion_Ultimo_Audio",
        "Solicitud_ID",
        "Google_Sheets_Row_ID",
        "Google_Drive_Folder_ID",
        "Google_Drive_File_IDs",
        "Source_Version_ID",
        "Last_Runtime_Trace_ID",
        "Followups_Enviados",
        "Proximo_Followup",
    }

    specs = {spec.key: spec for spec in FIELD_SPECS}
    assert all(specs[key].ai_can_write is False for key in locked)
    assert specs["Plan_Credito"].ai_can_write is True
    assert specs["Moto"].ai_can_write is True


def test_archive_field_options_marks_legacy_fields_without_deleting_metadata() -> None:
    options = archive_field_options({"choices": ["12m", "24m"]}, reason="legacy_plan")

    assert options["choices"] == ["12m", "24m"]
    assert options["deprecated"] is True
    assert options["visibility"] == "admin"
    assert options["archived_by_seed"]["source"] == SEED_ID
    assert options["archived_by_seed"]["reason"] == "legacy_plan"


def test_parse_docs_per_plan_reads_all_six_plans_from_requirements_source() -> None:
    requirements = load_requirements(REQUIREMENTS_PATH)
    docs_per_plan = parse_docs_per_plan(requirements)

    assert set(docs_per_plan) == set(PLAN_CREDITO_CHOICES)
    assert docs_per_plan["Sin Comprobantes"] == [
        "ine_ambos_lados",
        "comprobante_domicilio",
    ]
    assert "recibos_nomina_2_meses" in docs_per_plan["Nómina Recibos"]
    assert "nomina_1_mes_dentro_estado_cuenta" in docs_per_plan["Guardia de Seguridad"]


def test_parse_docs_per_plan_skips_disabled_malformed_and_empty_entries() -> None:
    docs_per_plan = parse_docs_per_plan(
        {
            "planes": [
                "not-a-plan",
                {"activo": False, "tipo_credito": "Disabled"},
                {"tipo_credito": "", "documentos_requeridos": []},
                {
                    "tipo_credito": "Valid",
                    "documentos_requeridos": [
                        "not-a-doc",
                        {"documento_id": "ine_ambos_lados"},
                        {"doc_id": "comprobante_domicilio"},
                        {"documento_id": "ine_ambos_lados"},
                    ],
                },
            ],
        }
    )

    assert docs_per_plan == {
        "Valid": ["ine_ambos_lados", "comprobante_domicilio"],
    }


def test_pipeline_definition_matches_dinamo_v1_stages_and_terminal_locks() -> None:
    docs_per_plan = parse_docs_per_plan(load_requirements(REQUIREMENTS_PATH))
    definition = build_pipeline_definition(docs_per_plan)
    stages = {stage["id"]: stage for stage in definition["stages"]}

    assert definition["metadata"]["source"] == SEED_ID
    assert list(stages) == [
        "nuevos",
        "plan",
        "cliente_potencial",
        "papeleria_incompleta",
        "papeleria_completa",
        "revision_humana",
        "no_califica",
        "cerrado_perdido",
        "cerrado_ganado",
    ]
    assert stages["nuevos"]["default"] is True
    assert stages["revision_humana"]["workflow_enter_only"] is True
    assert stages["no_califica"]["is_terminal"] is True
    assert stages["cerrado_ganado"]["automation_policy"]["write_owner"] == "human_admin_only"
    assert definition["docs_per_plan"]["Sin Comprobantes"] == [
        "ine_ambos_lados",
        "comprobante_domicilio",
    ]


def test_templates_use_takeover_invisible_language_and_declared_variables() -> None:
    templates = {spec.name: spec for spec in TEMPLATE_SPECS}
    all_body = "\n".join(spec.body for spec in TEMPLATE_SPECS)

    assert "te paso con Francisco" not in all_body
    assert "te paso con Frank" not in all_body
    assert "Déjame revisarlo bien" in templates["dinamo_handoff_general_v1"].body
    assert templates["dinamo_document_invalid_v1"].variables == ("motivo",)
    assert templates["dinamo_followup_12h_v1"].variables == (
        "Moto",
        "Plan_Credito_Sentence",
    )


def test_handoff_reason_choices_match_plan() -> None:
    assert HANDOFF_REASON_CHOICES == (
        "pago_reportado",
        "humano_solicitado",
        "expediente_completo",
        "documento_dudoso",
        "enojo_fuerte",
        "excepcion_no_cubierta",
        "conflicto_promesa_externa",
        "fuera_de_nl",
        "otro",
    )


def test_workflow_specs_are_dry_run_safe_and_customer_message_is_the_only_copy_path() -> None:
    workflows = {spec.key: spec for spec in build_workflow_specs()}

    assert workflows["state.write_contact_field"].trigger_type == "field_extracted"
    assert workflows["handoff.start"].event_type == "human_handoff_requested"
    assert workflows["followup.schedule"].nodes[0]["config"]["attempt_delays_hours"] == [3, 12, 72]
    assert workflows["followup.schedule"].nodes[0]["config"]["quiet_hours"] == {
        "timezone": "America/Mexico_City",
        "start": "23:00",
        "end": "07:00",
    }

    customer_copy_workflows = [
        spec.key for spec in workflows.values() if spec.customer_message_request_only
    ]
    assert customer_copy_workflows == ["customer_message.request"]
    assert workflows["customer_message.request"].nodes[0]["type"] == "template_message"


def test_tool_bindings_require_fact_tools_without_side_effects() -> None:
    tools = build_tool_binding_specs()

    assert tools["catalog.search"]["required"] is True
    assert tools["quote.resolve"]["required"] is True
    assert tools["requirements.lookup"]["required"] is True
    assert tools["catalog.search"]["description"]
    assert tools["faq.lookup"]["required"] is False
    assert all(spec["metadata_json"]["fact_only"] is True for spec in tools.values())


def test_agent_payload_exposes_runtime_direct_policy_bindings() -> None:
    payload = build_agent_payload()

    tool_bindings = payload["tool_policy"]["bindings"]
    field_definitions = payload["field_policy"]["fields"]
    workflow_bindings = payload["workflow_policy"]["bindings"]

    assert {binding["tool_name"] for binding in tool_bindings} == set(
        build_tool_binding_specs()
    )
    assert all(binding["description"] for binding in tool_bindings)
    assert all(binding["dry_run_only"] is True for binding in tool_bindings)
    assert {field["field_key"] for field in field_definitions} == {
        spec.key for spec in FIELD_SPECS
    }
    assert next(
        field for field in field_definitions if field["field_key"] == "Autorizado"
    )["writable"] is False
    assert next(
        field for field in field_definitions if field["field_key"] == "Moto"
    )["write_policy"] == "ai_auto"
    assert next(
        field for field in field_definitions if field["field_key"] == "Moto"
    )["write_policy_metadata"]["tool_evidence_required"] == [
        "catalog.search",
        "quote.resolve",
    ]
    assert {binding["binding_name"] for binding in workflow_bindings} == {
        spec.key for spec in build_workflow_specs()
    }
    assert all(binding["side_effects_allowed"] is False for binding in workflow_bindings)


def test_dry_run_preview_reports_no_send_configuration_without_db() -> None:
    result = preview_dinamo_v1_seed(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert result.dry_run is True
    assert result.pipeline_action == "would_create_or_update"
    assert result.deployment_action == "would_create_or_update_no_send"
    assert result.created_fields == [spec.key for spec in FIELD_SPECS]
    assert "catalog.search" in result.created_tool_bindings
    assert "customer_message.request" in result.created_workflows


async def test_db_seed_boundaries_create_safe_dinamo_phase_a_rows() -> None:
    tenant_id = uuid4()
    legacy = CustomerFieldDefinition(
        id=uuid4(),
        tenant_id=tenant_id,
        key="plan_credito",
        label="Plan viejo",
        field_type="select",
        field_options={"choices": ["12m", "24m", "36m", "48m"]},
        ordering=1,
    )
    result = seed_module.SeedResult(tenant_id=str(tenant_id), dry_run=False)

    await seed_module._seed_fields(
        FakeSession(FakeResult(values=[legacy])),
        tenant_id=tenant_id,
        result=result,
    )

    assert legacy.field_options["deprecated"] is True
    assert result.archived_fields == ["plan_credito"]
    assert "Plan_Credito" in result.created_fields

    docs_per_plan = parse_docs_per_plan(load_requirements(REQUIREMENTS_PATH))
    pipeline_session = FakeSession(FakeResult(scalar=None), FakeResult(scalar=1))
    await seed_module._seed_pipeline(
        pipeline_session,
        tenant_id=tenant_id,
        docs_per_plan=docs_per_plan,
        result=result,
    )
    pipeline = pipeline_session.added[0]
    assert pipeline.active is True
    assert pipeline.definition["metadata"]["source"] == SEED_ID
    assert result.pipeline_action == "created_new_active"

    template_session = FakeSession(FakeResult(values=[]))
    await seed_module._seed_templates(
        template_session,
        tenant_id=tenant_id,
        result=result,
    )
    assert {row.status for row in template_session.added} == {"draft"}

    agent_session = FakeSession(FakeResult(values=[]))
    agent = await seed_module._seed_agent(
        agent_session,
        tenant_id=tenant_id,
        result=result,
    )
    assert agent.status == "draft"
    assert agent.ops_config[SEED_ID]["live_scope"] == "none"

    version_session = FakeSession(FakeResult(values=[]))
    version = await seed_module._seed_agent_version(
        version_session,
        tenant_id=tenant_id,
        agent=agent,
        result=result,
    )
    assert version.status == "draft"
    assert version.snapshot["source"] == SEED_ID

    deployment_session = FakeSession(FakeResult(scalar=None))
    await seed_module._seed_deployment(
        deployment_session,
        tenant_id=tenant_id,
        agent=agent,
        version=version,
        result=result,
    )
    deployment = deployment_session.added[0]
    assert deployment.runtime_mode == "no_send"
    assert deployment.send_enabled is False
    assert deployment.workflow_side_effects_enabled is False

    workflow_session = FakeSession(FakeResult(values=[]))
    workflows = await seed_module._seed_workflows(
        workflow_session,
        tenant_id=tenant_id,
        result=result,
    )
    assert set(workflows) == {spec.key for spec in build_workflow_specs()}
    assert all(workflow.active is False for workflow in workflows.values())

    permission_session = FakeSession(FakeResult(values=[]))
    await seed_module._seed_field_permissions(
        permission_session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    permissions = {row.field_key: row for row in permission_session.added}
    assert permissions["Autorizado"].can_write is False
    assert permissions["Plan_Enganche"].can_write is False
    assert permissions["Plan_Credito"].can_write is True

    tool_session = FakeSession(FakeResult(values=[]))
    await seed_module._seed_tool_bindings(
        tool_session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    tool_bindings = {row.tool_name: row for row in tool_session.added}
    assert tool_bindings["quote.resolve"].required is True
    assert tool_bindings["faq.lookup"].required is False

    workflow_binding_session = FakeSession(FakeResult(values=[]))
    await seed_module._seed_workflow_bindings(
        workflow_binding_session,
        tenant_id=tenant_id,
        version=version,
        workflows=workflows,
        result=result,
    )
    assert workflow_binding_session.added
    assert all(row.execution_mode == "dry_run_only" for row in workflow_binding_session.added)
    assert all(row.side_effects_allowed is False for row in workflow_binding_session.added)
    assert all(
        row.customer_visible_output_allowed is False
        for row in workflow_binding_session.added
    )


async def test_db_seed_boundaries_update_existing_seeded_rows_safely() -> None:
    tenant_id = uuid4()
    result = seed_module.SeedResult(tenant_id=str(tenant_id), dry_run=False)
    seeded_pipeline = seed_module.TenantPipeline(
        id=uuid4(),
        tenant_id=tenant_id,
        version=7,
        definition={"metadata": {"source": SEED_ID}, "stages": []},
        active=True,
        history=[],
    )
    await seed_module._seed_pipeline(
        FakeSession(FakeResult(scalar=seeded_pipeline)),
        tenant_id=tenant_id,
        docs_per_plan={"Sin Comprobantes": ["ine_ambos_lados"]},
        result=result,
    )
    assert result.pipeline_action == "updated_active_seeded"
    assert seeded_pipeline.definition["docs_per_plan"] == {
        "Sin Comprobantes": ["ine_ambos_lados"],
    }

    agent = Agent(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Old",
        role="sales",
        status="production",
        ops_config={SEED_ID: {"agent": True}},
    )
    updated_agent = await seed_module._seed_agent(
        FakeSession(FakeResult(values=[agent])),
        tenant_id=tenant_id,
        result=result,
    )
    assert updated_agent is agent
    assert updated_agent.status == "draft"
    assert updated_agent.ops_config[SEED_ID]["source_version_id"] == SOURCE_VERSION_ID

    version = AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent.id,
        version_number=3,
        status="draft",
        snapshot={"source": SEED_ID},
    )
    updated_version = await seed_module._seed_agent_version(
        FakeSession(FakeResult(values=[version])),
        tenant_id=tenant_id,
        agent=agent,
        result=result,
    )
    assert updated_version is version
    assert updated_version.workflow_policy["execution_mode"] == "dry_run_only"

    workflow = Workflow(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Old handoff",
        trigger_type="manual",
        definition={"metadata": {"source": SEED_ID, "workflow_key": "handoff.start"}},
        active=True,
    )
    workflows = await seed_module._seed_workflows(
        FakeSession(FakeResult(values=[workflow])),
        tenant_id=tenant_id,
        result=result,
    )
    assert workflows["handoff.start"] is workflow
    assert workflow.active is False
    assert workflow.trigger_type == "human_handoff_requested"


async def test_seed_dinamo_v1_orchestrates_all_phase_a_steps_with_fake_session() -> None:
    tenant_id = uuid4()
    session = FakeSession(
        FakeResult(values=[]),  # fields
        FakeResult(scalar=None),  # active pipeline
        FakeResult(scalar=1),  # next pipeline version
        FakeResult(values=[]),  # templates
        FakeResult(values=[]),  # agent
        FakeResult(values=[]),  # agent version
        FakeResult(scalar=None),  # deployment
        FakeResult(values=[]),  # workflows
        FakeResult(values=[]),  # field permissions
        FakeResult(values=[]),  # tool bindings
        FakeResult(values=[]),  # workflow bindings
    )

    result = await seed_module.seed_dinamo_v1(
        session,
        tenant_id=tenant_id,
        requirements_path=REQUIREMENTS_PATH,
    )

    assert result.dry_run is False
    assert result.pipeline_action == "created_new_active"
    assert result.deployment_action == "created_no_send"
    assert result.agent_action == "created"
    assert result.version_action == "created"
    assert session.flush_count >= 1


async def test_seed_dinamo_v1_dry_run_uses_preview_without_session_queries() -> None:
    tenant_id = uuid4()
    session = FakeSession()

    result = await seed_module.seed_dinamo_v1(
        session,
        tenant_id=tenant_id,
        requirements_path=REQUIREMENTS_PATH,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.created_fields == [spec.key for spec in FIELD_SPECS]
    assert session.results == []
    assert session.added == []


async def test_update_branches_keep_seed_idempotent_and_no_live() -> None:
    tenant_id = uuid4()
    result = seed_module.SeedResult(tenant_id=str(tenant_id), dry_run=False)
    active_plan = CustomerFieldDefinition(
        id=uuid4(),
        tenant_id=tenant_id,
        key="Plan_Credito",
        label="Old Plan",
        field_type="text",
        field_options={},
        ordering=999,
    )
    duplicate_plan = CustomerFieldDefinition(
        id=uuid4(),
        tenant_id=tenant_id,
        key="Plan_Credito",
        label="Duplicate",
        field_type="text",
        field_options={},
        ordering=1000,
    )
    await seed_module._seed_fields(
        FakeSession(FakeResult(values=[active_plan, duplicate_plan])),
        tenant_id=tenant_id,
        result=result,
    )
    assert active_plan.label == "Plan Credito"
    assert active_plan.field_options["source"] == SEED_ID
    assert duplicate_plan.field_options["deprecated"] is True
    assert "Plan_Credito" in result.updated_fields

    active_pipeline = seed_module.TenantPipeline(
        id=uuid4(),
        tenant_id=tenant_id,
        version=2,
        definition={"metadata": {"source": "legacy"}},
        active=True,
        history=[],
    )
    await seed_module._seed_pipeline(
        FakeSession(FakeResult(scalar=active_pipeline), FakeResult(scalar=3)),
        tenant_id=tenant_id,
        docs_per_plan={},
        result=result,
    )
    assert active_pipeline.active is False

    existing_template = seed_module.WhatsAppTemplate(
        id=uuid4(),
        tenant_id=tenant_id,
        name="dinamo_handoff_general_v1",
        category="marketing",
        status="approved",
        language="en_US",
        body="old",
        variables=[],
    )
    await seed_module._seed_templates(
        FakeSession(FakeResult(values=[existing_template])),
        tenant_id=tenant_id,
        result=result,
    )
    assert existing_template.status == "draft"
    assert existing_template.language == "es_MX"
    assert existing_template.body.startswith("Déjame")

    agent = Agent(id=uuid4(), tenant_id=tenant_id, name="Francisco", role="sales")
    version = AgentVersion(id=uuid4(), tenant_id=tenant_id, agent_id=agent.id, version_number=1)
    existing_deployment = seed_module.AgentDeployment(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent.id,
        active_version_id=None,
        name="Unsafe",
        channel="test_lab",
        environment="no_send",
        send_enabled=True,
        workflow_side_effects_enabled=True,
    )
    await seed_module._seed_deployment(
        FakeSession(FakeResult(scalar=existing_deployment)),
        tenant_id=tenant_id,
        agent=agent,
        version=version,
        result=result,
    )
    assert existing_deployment.active_version_id == version.id
    assert existing_deployment.send_enabled is False
    assert existing_deployment.workflow_side_effects_enabled is False

    existing_permission = seed_module.AgentFieldPermission(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        field_key="Autorizado",
        can_read=False,
        can_write=True,
        evidence_required=False,
    )
    await seed_module._seed_field_permissions(
        FakeSession(FakeResult(values=[existing_permission])),
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    assert existing_permission.can_read is True
    assert existing_permission.can_write is False
    assert existing_permission.evidence_required is True

    existing_tool = seed_module.AgentToolBinding(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        tool_name="quote.resolve",
        enabled=False,
        required=False,
    )
    await seed_module._seed_tool_bindings(
        FakeSession(FakeResult(values=[existing_tool])),
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    assert existing_tool.enabled is True
    assert existing_tool.required is True

    workflow = Workflow(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Handoff",
        trigger_type="human_handoff_requested",
    )
    existing_binding = seed_module.AgentWorkflowBinding(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        workflow_id=workflow.id,
        event_type="human_handoff_requested",
        enabled=False,
        execution_mode="disabled",
        side_effects_allowed=True,
        customer_visible_output_allowed=True,
    )
    await seed_module._seed_workflow_bindings(
        FakeSession(FakeResult(values=[existing_binding])),
        tenant_id=tenant_id,
        version=version,
        workflows={"handoff.start": workflow},
        result=result,
    )
    assert existing_binding.enabled is True
    assert existing_binding.execution_mode == "dry_run_only"
    assert existing_binding.side_effects_allowed is False
    assert existing_binding.customer_visible_output_allowed is False


async def test_main_dry_run_prints_preview_without_db(capsys) -> None:
    code = await seed_module._main(
        UUID("00000000-0000-0000-0000-000000000001"),
        REQUIREMENTS_PATH,
        True,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert '"dry_run": true' in captured.out
    assert "would_create_or_update_no_send" in captured.out


async def test_main_non_dry_uses_session_factory_and_commits(monkeypatch, capsys) -> None:
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    session = FakeSession(
        FakeResult(values=[]),
        FakeResult(scalar=None),
        FakeResult(scalar=1),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(scalar=None),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
        FakeResult(values=[]),
    )

    import atendia.db.session as db_session

    monkeypatch.setattr(db_session, "_get_factory", lambda: lambda: FakeSessionContext(session))

    code = await seed_module._main(tenant_id, REQUIREMENTS_PATH, False)

    captured = capsys.readouterr()
    assert code == 0
    assert session.commit_count == 1
    assert '"dry_run": false' in captured.out


def test_main_parses_args_and_runs_dry_preview(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_dinamo_v1",
            "--tenant-id",
            "00000000-0000-0000-0000-000000000001",
            "--dry-run",
        ],
    )

    assert seed_module.main() == 0
    assert '"dry_run": true' in capsys.readouterr().out

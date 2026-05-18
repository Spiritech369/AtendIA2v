"""Smoke tests for the motos-crédito pipeline seed.

The seed is a hand-authored dict shipped as the recommended starter
config for tenants in the moto-credit niche. We don't test the SQL
install path here (DB-dependent integration test would live in
core/tests/integration/); we DO test that:

  1. The dict validates against PipelineDefinition (catches typos in
     stage ids, missing required fields on AutoEnterRules, etc.).
  2. The plan keys in docs_per_plan all reference doc keys that
     appear in documents_catalog.
  3. `lookup_requirements` returns the expected RequirementsResult
     for each plan when the customer hasn't sent any docs yet —
     i.e. the contract between the seed and the Fase 2 tool holds.

Treat this as a canary: if you rename a plan, change a doc key, or
drop a catalog entry, this test fails and forces the related code
paths to be updated together.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atendia.contracts.conversation_state import ConversationState
from atendia.contracts.pipeline_definition import (
    DocumentSpec,
    PipelineDefinition,
)
from atendia.contracts.extracted_fields import ExtractedFields
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.runner.flow_router import AlwaysTrigger, FlowModeRule, pick_flow_mode
from atendia.state_machine.motos_credito_pipeline import (
    MOTOS_CREDITO_AGENT_FLOW_MODE_RULES,
    MOTOS_CREDITO_DOCS_PER_PLAN,
    MOTOS_CREDITO_DOCUMENTS_CATALOG,
    MOTOS_CREDITO_PIPELINE_DEFINITION,
)
from atendia.state_machine.orchestrator import process_turn
from atendia.tools.lookup_requirements import (
    RequirementsResult,
    lookup_requirements,
)


def test_seed_validates_as_pipeline_definition():
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    assert pipeline.version == 1
    stage_ids = [s.id for s in pipeline.stages]
    assert stage_ids == [
        "nuevo_lead",
        "calificacion_inicial",
        "plan_seleccionado",
        "papeleria_incompleta",
        "papeleria_completa",
        "revision_humana",
    ]
    # Last stage is terminal so manual handoff can't bounce backwards.
    assert pipeline.stages[-1].is_terminal is True


def test_seed_flow_mode_rules_live_in_agent_config():
    """The moto router rules belong to Agent IA, not the pipeline JSON."""
    assert "flow_mode_rules" not in MOTOS_CREDITO_PIPELINE_DEFINITION

    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    assert pipeline.flow_mode_rules
    assert isinstance(pipeline.flow_mode_rules[-1].trigger, AlwaysTrigger)

    fallback_decision = pick_flow_mode(
        rules=pipeline.flow_mode_rules,
        extracted=ExtractedFields(),
        nlu=NLUResult(
            intent=Intent.GREETING,
            sentiment=Sentiment.NEUTRAL,
            confidence=0.95,
        ),
        vision=None,
        inbound_text="hola, quiero una moto a credito",
        pending_confirmation=None,
    )
    assert fallback_decision.mode.value == "SUPPORT"

    agent_rules = [
        FlowModeRule.model_validate(rule)
        for rule in MOTOS_CREDITO_AGENT_FLOW_MODE_RULES["rules"]
    ]
    assert isinstance(agent_rules[-1].trigger, AlwaysTrigger)

    decision = pick_flow_mode(
        rules=agent_rules,
        extracted=ExtractedFields(),
        nlu=NLUResult(
            intent=Intent.GREETING,
            sentiment=Sentiment.NEUTRAL,
            confidence=0.95,
        ),
        vision=None,
        inbound_text="hola, quiero una moto a credito",
        pending_confirmation=None,
    )
    assert decision.mode.value == "PLAN"


def test_seed_text_fields_can_move_out_of_nuevo_lead():
    """First-stage text must be enough for NLU + auto-enter to qualify leads."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    nuevo_lead = next(s for s in pipeline.stages if s.id == "nuevo_lead")
    required_names = {f.name for f in nuevo_lead.required_fields}
    assert "antiguedad_laboral_meses" in required_names

    calificacion = next(s for s in pipeline.stages if s.id == "calificacion_inicial")
    assert calificacion.auto_enter_rules is not None
    fields = {c.field for c in calificacion.auto_enter_rules.conditions}
    assert "antiguedad_laboral_meses" in fields
    assert "cumple_antiguedad" not in fields


def test_every_stage_can_answer_every_classifier_intent():
    """Every stage needs at least one executable action.

    The classifier can return any Intent from any stage. The action
    resolver should prefer the intent-specific action when available,
    but the orchestrator must still pick an allowed fallback action when
    the stage is intentionally narrow, such as revision_humana.
    """
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)

    for stage in pipeline.stages:
        assert stage.actions_allowed, f"{stage.id} has no actions_allowed"
        for intent in Intent:
            state = ConversationState(
                conversation_id=f"test-{stage.id}-{intent.value}",
                tenant_id="tenant-test",
                current_stage=stage.id,
                extracted_data={},
                stage_entered_at=datetime.now(timezone.utc),
            )
            nlu = NLUResult(
                intent=intent,
                sentiment=Sentiment.NEUTRAL,
                confidence=0.95,
            )

            decision = process_turn(pipeline, state, nlu, turn_count=1)

            target_stage = next(s for s in pipeline.stages if s.id == decision.next_stage)
            assert decision.action in target_stage.actions_allowed, (
                f"{stage.id} + {intent.value} resolved to {decision.action!r}, "
                f"not allowed by target stage {target_stage.id}: {target_stage.actions_allowed}"
            )


def test_every_doc_in_docs_per_plan_appears_in_catalog():
    """If you reference a DOCS_X in docs_per_plan but forget to add
    the spec to documents_catalog, the contact panel renders the raw
    key as label. That's recoverable (the tool tolerates it), but for
    the curated seed we want both halves to stay in sync."""
    catalog_keys = {d["key"] for d in MOTOS_CREDITO_DOCUMENTS_CATALOG}
    referenced: set[str] = set()
    for docs in MOTOS_CREDITO_DOCS_PER_PLAN.values():
        referenced.update(docs)
    missing = referenced - catalog_keys
    assert not missing, f"docs referenced by plans but absent from catalog: {missing}"


def test_documents_catalog_specs_are_valid():
    """Each catalog entry must satisfy DocumentSpec — keys must match
    DOCS_<UPPERCASE_UNDERSCORE>, label non-empty, hint ≤ 200 chars."""
    for entry in MOTOS_CREDITO_DOCUMENTS_CATALOG:
        DocumentSpec.model_validate(entry)


def test_lookup_requirements_for_each_seeded_plan():
    """Every seeded plan must produce a RequirementsResult (not a
    ToolNoDataResult) and list all its required docs as `missing`
    when the customer has no docs yet — the bot's first request."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    for plan_key, doc_keys in MOTOS_CREDITO_DOCS_PER_PLAN.items():
        result = lookup_requirements(
            pipeline=pipeline,
            plan_credito=plan_key,
            customer_attrs={},
        )
        assert isinstance(result, RequirementsResult), (
            f"plan {plan_key!r} unexpectedly produced no_data"
        )
        assert [d.key for d in result.required] == doc_keys
        assert [d.key for d in result.missing] == doc_keys
        assert result.received == []
        assert result.complete is False


def test_lookup_requirements_complete_when_all_docs_ok():
    """The papeleria_completa stage's auto_enter_rule fires on
    docs_complete_for_plan; this confirms `lookup_requirements` agrees
    with the evaluator's notion of 'complete' on the same input."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    plan = "sin_comprobantes_25"
    attrs = {key: {"status": "ok"} for key in MOTOS_CREDITO_DOCS_PER_PLAN[plan]}
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito=plan,
        customer_attrs=attrs,
    )
    assert isinstance(result, RequirementsResult)
    assert result.complete is True
    assert result.missing == []


def test_vision_doc_mapping_targets_only_catalog_keys():
    """Every DOCS_* key referenced in vision_doc_mapping must exist in
    documents_catalog — otherwise the Fase 3 helper writes to a key the
    `docs_complete_for_plan` evaluator doesn't track, and papelería
    completa silently never fires."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    catalog_keys = {d["key"] for d in MOTOS_CREDITO_DOCUMENTS_CATALOG}
    for category, keys in pipeline.vision_doc_mapping.items():
        for k in keys:
            assert k in catalog_keys, (
                f"vision_doc_mapping[{category!r}] references {k!r} but it's not in the catalog"
            )


def test_vision_doc_mapping_covers_every_doc_category_seed_uses():
    """Sanity check that each doc category used by the seed has a
    Vision mapping; categories the seed deliberately skips (factura)
    are documented in the module docstring."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    expected_categories = {
        "ine",
        "comprobante",
        "recibo_nomina",
        "estado_cuenta",
        "constancia_sat",
        "imss",
    }
    assert expected_categories.issubset(pipeline.vision_doc_mapping.keys())


def test_papeleria_completa_stage_triggers_auto_handoff():
    """Fase 4 contract: the moto seed marks Papelería completa as the
    auto-handoff trigger. Drifting this flag silently turns off the
    handoff for every tenant on the seed."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    completa = next(s for s in pipeline.stages if s.id == "papeleria_completa")
    assert completa.pause_bot_on_enter is True
    assert completa.handoff_reason == "docs_complete_for_plan"


def test_papeleria_incompleta_stage_uses_doc_keys_consistently():
    """The auto_enter_rule on papeleria_incompleta lists `DOCS_X.status`
    conditions that must match real catalog keys — drifting one without
    updating the other would silently never auto-enter."""
    pipeline = PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)
    incompleta = next(s for s in pipeline.stages if s.id == "papeleria_incompleta")
    assert incompleta.auto_enter_rules is not None
    catalog_keys = {d["key"] for d in MOTOS_CREDITO_DOCUMENTS_CATALOG}
    for cond in incompleta.auto_enter_rules.conditions:
        # cond.field looks like "DOCS_INE_FRENTE.status"; strip the suffix
        doc_key = cond.field.split(".", 1)[0]
        assert doc_key in catalog_keys, (
            f"auto_enter_rule references {doc_key} but it's not in the catalog"
        )

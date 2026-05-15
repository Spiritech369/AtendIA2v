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

from atendia.contracts.pipeline_definition import (
    DocumentSpec,
    PipelineDefinition,
)
from atendia.state_machine.motos_credito_pipeline import (
    MOTOS_CREDITO_DOCS_PER_PLAN,
    MOTOS_CREDITO_DOCUMENTS_CATALOG,
    MOTOS_CREDITO_PIPELINE_DEFINITION,
)
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

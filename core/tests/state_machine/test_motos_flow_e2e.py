"""Narrative end-to-end walk-through of the motos crédito flow.

This is the "Fase 7" canary: it exercises the contracts the runner
glues together (NLU output → apply_ai_extractions → auto_enter_rules
→ pipeline_evaluator → lookup_requirements → apply_vision_to_attrs
→ stage_entry_handoff) **without** spinning up a real Postgres / arq.

Each test follows one stage of the user's flow:

  1. Saludo inicial → "tengo 8 meses" → cumple_antiguedad=true
  2. Selección de plan → plan_credito persiste → lookup_requirements
  3. Envío de INE → Vision quality_check → DOCS_INE_FRENTE.status=ok
  4. Última papelería → docs_complete_for_plan flips true → handoff

The walk-through uses the seeded motos pipeline + the same helpers
the runner imports, so any drift in those helpers will be caught
without requiring a full integration harness.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.contracts.vision_result import (
    DocumentSide,
    VisionCategory,
    VisionQualityCheck,
    VisionResult,
)
from atendia.runner.ai_extraction_service import apply_ai_extractions
from atendia.runner.field_extraction_mapping import (
    Action,
    decide_action,
    map_entity_to_attr,
)
from atendia.runner.vision_to_attrs import apply_vision_to_attrs
from atendia.state_machine.motos_credito_pipeline import (
    MOTOS_CREDITO_PIPELINE_DEFINITION,
)
from atendia.state_machine.pipeline_evaluator import (
    evaluate_rule_group,
)
from atendia.tools.lookup_requirements import (
    RequirementsResult,
    lookup_requirements,
)

# ---------------------------------------------------------------------------
# Test infrastructure: a fake session/customer pair so the helpers
# behave as in production but without a DB round-trip.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, customer_attrs: dict[str, Any] | None = None) -> None:
        self.customer = MagicMock()
        self.customer.id = uuid4()
        self.customer.attrs = dict(customer_attrs or {})
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _stmt: Any, _params: Any = None) -> Any:
        class _R:
            def __init__(self, value: Any) -> None:
                self._v = value

            def scalar_one_or_none(self) -> Any:
                return self._v

        return _R(self.customer)

    async def flush(self) -> None:
        return None


@pytest.fixture
def pipeline() -> PipelineDefinition:
    return PipelineDefinition.model_validate(MOTOS_CREDITO_PIPELINE_DEFINITION)


# ---------------------------------------------------------------------------
# 1 — Saludo inicial → cliente declara antigüedad → cumple_antiguedad=true
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_1_antiguedad_writes_attr_and_satisfies_calificacion_rule(pipeline):
    """NLU should extract antigüedad_laboral_meses + cumple_antiguedad
    and the calificacion_inicial stage's auto_enter_rule should match."""
    session = _FakeSession()
    entities = {
        "labor_seniority": ExtractedField(
            value=8,
            confidence=0.92,
            source_turn=1,
        ),
    }
    applied = await apply_ai_extractions(
        session=session,
        tenant_id=uuid4(),
        customer_id=session.customer.id,
        conversation_id=uuid4(),
        turn_number=1,
        entities=entities,
        inbound_text="tengo 8 meses trabajando",
    )
    # AUTO write — antigüedad lands on attrs.
    assert [c.attr_key for c in applied] == ["antiguedad_laboral_meses"]
    assert session.customer.attrs["antiguedad_laboral_meses"] == 8

    # NLU also produces a derived boolean field cumple_antiguedad; the
    # production prompt drives this, but for the test we set it manually
    # since the helper under test isn't the NLU itself.
    session.customer.attrs["cumple_antiguedad"] = True

    # Now the calificacion_inicial stage's rule should match.
    calif = next(s for s in pipeline.stages if s.id == "calificacion_inicial")
    assert calif.auto_enter_rules is not None
    matched = evaluate_rule_group(
        calif.auto_enter_rules,
        session.customer.attrs,
    )
    assert matched is True


# ---------------------------------------------------------------------------
# 2 — Selección de plan → plan_credito persiste → lookup_requirements
# ---------------------------------------------------------------------------


def test_step_2_plan_selected_yields_requirements_list(pipeline):
    """When the customer picks 'nomina_tarjeta_10', lookup_requirements
    returns the 4 docs that plan needs, all in `missing`."""
    customer_attrs = {
        "cumple_antiguedad": True,
        "antiguedad_laboral_meses": 8,
        "tipo_credito": "Nómina Tarjeta",
        "plan_credito": "nomina_tarjeta_10",
    }
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="nomina_tarjeta_10",
        customer_attrs=customer_attrs,
    )
    assert isinstance(result, RequirementsResult)
    assert result.complete is False
    assert [d.key for d in result.missing] == [
        "DOCS_INE_FRENTE",
        "DOCS_INE_REVERSO",
        "DOCS_COMPROBANTE_DOMICILIO",
        "DOCS_ESTADOS_CUENTA_NOMINA",
    ]
    # Each missing doc carries a human-readable label from the catalog —
    # the composer uses these in the bot reply.
    assert all(d.label and not d.label.startswith("DOCS_") for d in result.missing)


# ---------------------------------------------------------------------------
# 3 — Cliente manda INE válida → vision_to_attrs marca status=ok
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_3_ine_front_image_writes_docs_ine_frente_ok(pipeline):
    """Vision quality_check.valid_for_credit_file=true + side=front →
    customer.attrs['DOCS_INE_FRENTE']={status:'ok', ...} ; the rest
    of the docs untouched, stage stays Papelería Incompleta until
    everything lands."""
    session = _FakeSession(
        customer_attrs={
            "plan_credito": "nomina_tarjeta_10",
            "cumple_antiguedad": True,
        }
    )
    vision = VisionResult(
        category=VisionCategory.INE,
        confidence=0.94,
        metadata={
            "ambos_lados": False,
            "legible": True,
            "fecha_iso": None,
            "institucion": None,
            "modelo": None,
            "notas": None,
        },
        quality_check=VisionQualityCheck(
            four_corners_visible=True,
            legible=True,
            not_blurry=True,
            no_flash_glare=True,
            not_cut=True,
            side=DocumentSide.FRONT,
            valid_for_credit_file=True,
            rejection_reason=None,
        ),
    )
    writes = await apply_vision_to_attrs(
        session=session,
        customer_id=session.customer.id,
        pipeline=pipeline,
        vision_result=vision,
    )
    assert [w.doc_key for w in writes] == ["DOCS_INE_FRENTE"]
    assert writes[0].accepted is True
    assert session.customer.attrs["DOCS_INE_FRENTE"]["status"] == "ok"
    # No spurious writes — DOCS_INE_REVERSO is still missing.
    assert "DOCS_INE_REVERSO" not in session.customer.attrs

    # Papelería incompleta auto_enter_rule (match='any') should fire on
    # any DOCS_*.status=ok — verify it picks up our new write.
    incompleta = next(s for s in pipeline.stages if s.id == "papeleria_incompleta")
    assert (
        evaluate_rule_group(
            incompleta.auto_enter_rules,
            session.customer.attrs,
        )
        is True
    )


@pytest.mark.asyncio
async def test_step_3b_rejected_image_writes_rejected_with_reason(pipeline):
    """Vision rejection → customer.attrs DOCS_X.status='rejected' with
    rejection_reason; lookup_requirements surfaces it under .rejected[]."""
    session = _FakeSession(
        customer_attrs={
            "plan_credito": "nomina_tarjeta_10",
        }
    )
    vision = VisionResult(
        category=VisionCategory.COMPROBANTE,
        confidence=0.88,
        metadata={
            "ambos_lados": False,
            "legible": False,
            "fecha_iso": None,
            "institucion": None,
            "modelo": None,
            "notas": "reflejo",
        },
        quality_check=VisionQualityCheck(
            four_corners_visible=True,
            legible=False,
            not_blurry=True,
            no_flash_glare=False,
            not_cut=True,
            side=DocumentSide.UNKNOWN,
            valid_for_credit_file=False,
            rejection_reason="se ve con reflejo, no se leen los datos",
        ),
    )
    writes = await apply_vision_to_attrs(
        session=session,
        customer_id=session.customer.id,
        pipeline=pipeline,
        vision_result=vision,
    )
    assert writes[0].accepted is False
    assert session.customer.attrs["DOCS_COMPROBANTE_DOMICILIO"]["status"] == "rejected"

    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="nomina_tarjeta_10",
        customer_attrs=session.customer.attrs,
    )
    assert isinstance(result, RequirementsResult)
    rejected = next(
        (d for d in result.rejected if d.key == "DOCS_COMPROBANTE_DOMICILIO"),
        None,
    )
    assert rejected is not None
    assert "reflejo" in rejected.rejection_reason


# ---------------------------------------------------------------------------
# 4 — Papelería completa → docs_complete_for_plan + handoff
# ---------------------------------------------------------------------------


def test_step_4_all_docs_ok_flips_complete_for_plan(pipeline):
    """When every doc the plan requires is status='ok', the
    docs_complete_for_plan operator evaluates true on the same attrs
    snapshot the runner reads."""
    customer_attrs = {
        "plan_credito": "nomina_tarjeta_10",
        "DOCS_INE_FRENTE": {"status": "ok"},
        "DOCS_INE_REVERSO": {"status": "ok"},
        "DOCS_COMPROBANTE_DOMICILIO": {"status": "ok"},
        "DOCS_ESTADOS_CUENTA_NOMINA": {"status": "ok"},
    }
    completa = next(s for s in pipeline.stages if s.id == "papeleria_completa")
    matched = evaluate_rule_group(
        completa.auto_enter_rules,
        customer_attrs,
        docs_per_plan=pipeline.docs_per_plan,
    )
    assert matched is True

    # And lookup_requirements agrees.
    result = lookup_requirements(
        pipeline=pipeline,
        plan_credito="nomina_tarjeta_10",
        customer_attrs=customer_attrs,
    )
    assert isinstance(result, RequirementsResult)
    assert result.complete is True
    assert result.missing == []
    assert result.rejected == []
    # The stage seed also marks pause_bot_on_enter=true with the right
    # reason, so when the runner's pipeline_evaluator promotes this
    # conversation to papeleria_completa, _trigger_stage_entry_handoff
    # will pause the bot + persist a HandoffSummary (covered by
    # test_stage_entry_handoff.py).
    assert completa.pause_bot_on_enter is True
    assert completa.handoff_reason == "docs_complete_for_plan"


# ---------------------------------------------------------------------------
# Bonus: confidence threshold ladder for "buy with confidence" decisions.
# ---------------------------------------------------------------------------


def test_confidence_ladder_matches_design_doc():
    """The threshold ladder lives in field_extraction_mapping and is
    referenced both by apply_ai_extractions and the contact panel's
    suggestion flow. Pin the numbers here so future tweaks are
    intentional."""
    # High confidence → AUTO write.
    assert decide_action(current_value=None, new_value="x", confidence=0.85) == Action.AUTO
    assert decide_action(current_value=None, new_value="x", confidence=0.95) == Action.AUTO
    # Medium → SUGGEST (lands in field_suggestions, never on attrs).
    assert decide_action(current_value=None, new_value="x", confidence=0.7) == Action.SUGGEST
    # Below 0.6 → SKIP.
    assert decide_action(current_value=None, new_value="x", confidence=0.59) == Action.SKIP


def test_entity_mapping_covers_motos_seed_keys():
    """The motos pipeline references plan_credito + tipo_credito +
    antiguedad_laboral_meses on customer.attrs; if the NLU mapping
    drifts so those keys can't be reached, the whole flow stalls."""
    for canonical in (
        "plan_credito",
        "tipo_credito",
        "antiguedad_laboral_meses",
        "modelo_interes",
        "marca",
    ):
        # Map via the entity_key the NLU prompt produces.
        if canonical == "marca":
            entity = "brand"
        elif canonical == "modelo_interes":
            entity = "model"
        elif canonical == "tipo_credito":
            entity = "tipo_credito"
        elif canonical == "plan_credito":
            entity = "plan_credito"
        elif canonical == "antiguedad_laboral_meses":
            entity = "labor_seniority"
        else:
            entity = canonical
        assert map_entity_to_attr(entity) == canonical

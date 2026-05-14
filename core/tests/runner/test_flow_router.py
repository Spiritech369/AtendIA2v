"""Tests for the deterministic flow router (Phase 3c.2).

Cubre: cada uno de los 8 trigger types, normalización, orden de
precedencia, error si no hay fallback always.
"""
import pytest

from atendia.contracts.extracted_fields import ExtractedFields, PlanCredito
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.vision_result import VisionCategory, VisionResult
from atendia.runner.flow_router import (
    AlwaysTrigger,
    FieldMissingTrigger,
    FieldPresentAndIntentTrigger,
    FlowModeRule,
    HasAttachmentTrigger,
    KeywordInTextTrigger,
    PendingConfirmationTrigger,
    _normalize_for_router,
    pick_flow_mode,
)


def _nlu(intent: Intent = Intent.UNCLEAR) -> NLUResult:
    return NLUResult(
        intent=intent, entities={}, sentiment=Sentiment.NEUTRAL,
        confidence=0.9, ambiguities=[],
    )


def _vision(category: VisionCategory = VisionCategory.INE) -> VisionResult:
    return VisionResult(category=category, confidence=0.9, metadata={})


# ---- Single-trigger tests ----------------------------------------------

def test_has_attachment_triggers_doc() -> None:
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=_vision(), inbound_text="aquí va",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.DOC


def test_no_attachment_skips_doc_rule() -> None:
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="hola",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.SUPPORT


def test_keyword_match_with_accents_stripped() -> None:
    """'mañana' en keyword list debe matchear 'manana' en input (sin tilde)."""
    rules = [
        FlowModeRule(id="r1",
                     trigger=KeywordInTextTrigger(list=["mañana", "luego"]),
                     mode=FlowMode.OBSTACLE),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="te lo paso manana",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.OBSTACLE


def test_keyword_match_case_insensitive() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=KeywordInTextTrigger(list=["gracias"]),
                     mode=FlowMode.RETENTION),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="GRACIAS por la info",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.RETENTION


def test_field_missing_triggers_when_field_is_none() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=FieldMissingTrigger(field="plan_credito"),
                     mode=FlowMode.PLAN),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.PLAN


def test_field_missing_skipped_when_field_present() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=FieldMissingTrigger(field="plan_credito"),
                     mode=FlowMode.PLAN),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    extracted = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    mode = pick_flow_mode(
        rules=rules, extracted=extracted,
        nlu=_nlu(), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.SUPPORT


def test_field_present_and_intent_combined() -> None:
    """SALES requiere plan_credito set AND intent in [ask_price, buy]."""
    rules = [
        FlowModeRule(id="r1",
                     trigger=FieldPresentAndIntentTrigger(
                         field="plan_credito",
                         intents=["ask_price", "buy"]),
                     mode=FlowMode.SALES),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    extracted = ExtractedFields(plan_credito=PlanCredito.PLAN_10)
    # Caso 1: plan + ask_price → SALES
    mode1 = pick_flow_mode(
        rules=rules, extracted=extracted,
        nlu=_nlu(intent=Intent.ASK_PRICE), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode1.mode == FlowMode.SALES
    # Caso 2: plan pero intent unrelated → SUPPORT
    mode2 = pick_flow_mode(
        rules=rules, extracted=extracted,
        nlu=_nlu(intent=Intent.GREETING), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode2.mode == FlowMode.SUPPORT
    # Caso 3: sin plan, ask_price → SUPPORT
    mode3 = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(intent=Intent.ASK_PRICE), vision=None, inbound_text="",
        pending_confirmation=None,
    )
    assert mode3.mode == FlowMode.SUPPORT


def test_pending_confirmation_trigger_for_binary_qa() -> None:
    rules = [
        FlowModeRule(id="r1",
                     trigger=PendingConfirmationTrigger(),
                     mode=FlowMode.PLAN),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="sí",
        pending_confirmation="is_nomina_tarjeta",
    )
    assert mode.mode == FlowMode.PLAN


# ---- Precedence + safety -----------------------------------------------

def test_first_match_wins_over_later() -> None:
    """Doc rule first → DOC, even if KeywordInText would also match."""
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="r2",
                     trigger=KeywordInTextTrigger(list=["mañana"]),
                     mode=FlowMode.OBSTACLE),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    mode = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=_vision(), inbound_text="te lo paso mañana",
        pending_confirmation=None,
    )
    assert mode.mode == FlowMode.DOC


def test_missing_always_fallback_raises() -> None:
    """Defensive: si nadie matchea, raise."""
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
    ]
    with pytest.raises(RuntimeError, match="always"):
        pick_flow_mode(
            rules=rules, extracted=ExtractedFields(),
            nlu=_nlu(), vision=None, inbound_text="hola",
            pending_confirmation=None,
        )


# ---- Rule id / trigger type (Migration 045 — DebugPanel) ----------------

def test_decision_carries_matched_rule_id_and_trigger_type() -> None:
    """DebugPanel needs to know which rule fired and what type. Migration 045
    exposes both on FlowDecision so the panel can render "Modo X because
    rule Y matched" without re-deriving rationale."""
    rules = [
        FlowModeRule(id="doc_attachment",
                     trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="fb", trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    decision = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=_vision(), inbound_text="aquí va",
        pending_confirmation=None,
    )
    assert decision.mode == FlowMode.DOC
    assert decision.rule_id == "doc_attachment"
    assert decision.trigger_type == "has_attachment"


def test_decision_for_always_fallback_reports_rule_id() -> None:
    rules = [
        FlowModeRule(id="r1", trigger=HasAttachmentTrigger(), mode=FlowMode.DOC),
        FlowModeRule(id="default_support",
                     trigger=AlwaysTrigger(), mode=FlowMode.SUPPORT),
    ]
    decision = pick_flow_mode(
        rules=rules, extracted=ExtractedFields(),
        nlu=_nlu(), vision=None, inbound_text="hola",
        pending_confirmation=None,
    )
    assert decision.mode == FlowMode.SUPPORT
    assert decision.rule_id == "default_support"
    assert decision.trigger_type == "always"


# ---- Normalization helper ----------------------------------------------

def test_normalize_lowercases() -> None:
    assert _normalize_for_router("HOLA Mundo") == "hola mundo"


def test_normalize_strips_accents() -> None:
    assert _normalize_for_router("mañana") == "manana"
    assert _normalize_for_router("comprobante con ñ") == "comprobante con n"

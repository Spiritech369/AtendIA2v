"""Unit tests for composer_prompts (Phase 3c.2: mode-based dispatch).

Two layers:
  * Structural invariants of SYSTEM_PROMPT_TEMPLATE / MODE_PROMPTS /
    build_composer_prompt / brand_facts pre-pass (this file's first half).
  * Byte-equality snapshot tests for 13 mode x state combinations
    (this file's second half). Regenerate fixtures via
    ``scripts/regen_mode_fixtures.py`` when prompts intentionally change.
"""
from pathlib import Path

import pytest

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import (
    MODE_PROMPTS,
    OUTPUT_INSTRUCTIONS,
    SYSTEM_PROMPT_TEMPLATE,
    _resolve_brand_facts_in_block,
    build_composer_prompt,
)
from atendia.runner.composer_protocol import ComposerInput

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "composer"

# ============================================================
# Template / constant invariants
# ============================================================

def test_system_prompt_has_required_placeholders() -> None:
    for ph in [
        "{{bot_name}}", "{{register}}", "{{use_emojis}}", "{{max_words}}",
        "{{forbidden_phrases}}", "{{signature_phrases}}",
        "{{turn_number}}", "{{stage}}", "{{last_intent}}", "{{extracted_data}}",
        "{{action_payload}}", "{{brand_facts_block}}", "{{mode_guidance}}",
        "{{output_instructions}}",
    ]:
        assert ph in SYSTEM_PROMPT_TEMPLATE


def test_mode_prompts_has_all_six_modes() -> None:
    assert set(MODE_PROMPTS.keys()) == set(FlowMode)


def test_mode_prompts_plan_says_no_inventes_precios() -> None:
    assert "NO inventes precios" in MODE_PROMPTS[FlowMode.PLAN]


def test_mode_prompts_sales_says_no_inventes_precios() -> None:
    assert "NO INVENTES precios" in MODE_PROMPTS[FlowMode.SALES]


def test_mode_prompts_doc_says_no_inventes() -> None:
    assert "NO inventes" in MODE_PROMPTS[FlowMode.DOC]


def test_mode_prompts_retention_carries_attempt_marker() -> None:
    assert "retention_attempt" in MODE_PROMPTS[FlowMode.RETENTION]


def test_output_instructions_mentions_messages_format() -> None:
    assert "messages" in OUTPUT_INSTRUCTIONS
    assert "{{max_messages}}" in OUTPUT_INSTRUCTIONS
    assert "{{max_words}}" in OUTPUT_INSTRUCTIONS


# ============================================================
# build_composer_prompt — structural
# ============================================================

def test_build_composer_prompt_basic_structure() -> None:
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.RETENTION,
        current_stage="sales",
        tone=Tone(bot_name="Dinamo", register="informal_mexicano"),
        history=[("inbound", "hola"), ("outbound", "qué onda")],
    ))
    assert msgs[0]["role"] == "system"
    assert "Dinamo" in msgs[0]["content"]
    assert "informal_mexicano" in msgs[0]["content"]
    assert "RETENTION MODE" in msgs[0]["content"]
    # History rendered as user/assistant chat messages
    assert any(m["role"] == "user" and "hola" in m["content"] for m in msgs)
    assert any(m["role"] == "assistant" and "qué onda" in m["content"] for m in msgs)


def test_build_composer_prompt_renders_turn_number() -> None:
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.RETENTION,
        current_stage="sales", turn_number=7, tone=Tone(),
    ))
    assert "Turno actual: 7" in msgs[0]["content"]


def test_build_composer_prompt_no_history_no_user_message() -> None:
    """Composer prompt does NOT append a user message at the end."""
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.RETENTION,
        current_stage="sales", tone=Tone(),
    ))
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"


def test_build_composer_prompt_renders_forbidden_phrases() -> None:
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.RETENTION,
        current_stage="sales",
        tone=Tone(forbidden_phrases=["estimado cliente"]),
    ))
    assert "estimado cliente" in msgs[0]["content"]


# ============================================================
# build_composer_prompt — mode dispatch
# ============================================================

def test_dispatch_picks_mode_specific_block() -> None:
    """SALES mode → SALES guidance, not PLAN guidance.

    Uses markers that are unique to each mode's body (not cross-references —
    PLAN's prompt mentions "SALES MODE" inside its prohibido section).
    """
    sales_msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.SALES,
        current_stage="sales",
        action_payload={"status": "ok", "name": "Adventure",
                        "price_contado_mxn": "29900"},
        brand_facts={"catalog_url": "https://x", "buro_max_amount": "$50 mil"},
        tone=Tone(),
    ))
    plan_msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.PLAN,
        current_stage="plan",
        brand_facts={"catalog_url": "https://x", "buro_max_amount": "$50 mil",
                     "post_completion_form": "https://y"},
        tone=Tone(),
    ))
    # SALES has the price reasoning + objection handling; PLAN does not.
    assert "Puedes liquidar antes sin penalización" in sales_msgs[0]["content"]
    assert "Puedes liquidar antes sin penalización" not in plan_msgs[0]["content"]
    # PLAN has the credit-type menu; SALES does not.
    assert "Me depositan nómina en tarjeta" in plan_msgs[0]["content"]
    assert "Me depositan nómina en tarjeta" not in sales_msgs[0]["content"]


def test_brand_facts_block_omitted_for_retention() -> None:
    """RETENTION + OBSTACLE skip brand_facts injection (token-bloat avoidance)."""
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.RETENTION,
        current_stage="sales",
        brand_facts={"catalog_url": "https://x"},
        tone=Tone(),
    ))
    assert "Brand facts" not in msgs[0]["content"]


def test_brand_facts_block_present_for_support() -> None:
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.SUPPORT,
        current_stage="plan",
        brand_facts={
            "address": "Benito Juárez 801",
            "human_agent_name": "Francisco",
            "buro_max_amount": "$50 mil",
            "approval_time_hours": "24",
            "delivery_time_days": "3-7",
        },
        tone=Tone(),
    ))
    assert "Brand facts" in msgs[0]["content"]
    assert "Benito Juárez 801" in msgs[0]["content"]
    # Sorted keys → address comes before human_agent_name
    assert msgs[0]["content"].index("address") < msgs[0]["content"].index("human_agent_name")


# ============================================================
# brand_facts pre-pass
# ============================================================

def test_resolve_brand_facts_substitutes_dotted_refs() -> None:
    block = "Catálogo: {{brand_facts.catalog_url}} y dirección: {{brand_facts.address}}"
    out = _resolve_brand_facts_in_block(
        block, {"catalog_url": "https://x", "address": "Calle 1"},
    )
    assert out == "Catálogo: https://x y dirección: Calle 1"


def test_resolve_brand_facts_raises_on_missing_key() -> None:
    """Non-empty facts dict missing the referenced key → fail loud."""
    block = "Catálogo: {{brand_facts.catalog_url}}"
    with pytest.raises(RuntimeError, match="catalog_url"):
        _resolve_brand_facts_in_block(block, {"address": "Calle 1"})


def test_resolve_brand_facts_empty_dict_leaves_literals() -> None:
    """Empty facts dict → no-op so callers without brand context still work."""
    block = "Catálogo: {{brand_facts.catalog_url}}"
    assert _resolve_brand_facts_in_block(block, {}) == block


def test_resolve_brand_facts_leaves_non_dotted_refs_alone() -> None:
    """Single-level placeholders like {{stage}} are render_template's job."""
    block = "Stage: {{stage}}, catalog: {{brand_facts.catalog_url}}"
    out = _resolve_brand_facts_in_block(block, {"catalog_url": "https://x"})
    assert "{{stage}}" in out
    assert "https://x" in out


def test_build_composer_prompt_substitutes_brand_facts_in_sales() -> None:
    """SALES mode_block has {{brand_facts.catalog_url}} — must be resolved."""
    msgs = build_composer_prompt(ComposerInput(
        action="unused", flow_mode=FlowMode.SALES,
        current_stage="sales",
        action_payload={"status": "no_data"},
        brand_facts={
            "catalog_url": "https://example.com/cat",
            "buro_max_amount": "$50 mil",
        },
        tone=Tone(),
    ))
    assert "https://example.com/cat" in msgs[0]["content"]
    assert "{{brand_facts.catalog_url}}" not in msgs[0]["content"]


# ============================================================
# Snapshot fixtures — byte-equality guards (T17)
#
# Regenerate after intentional prompt changes:
#   PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/regen_mode_fixtures.py
# ============================================================
_DINAMO_TONE = Tone(
    register="informal_mexicano", use_emojis="sparingly",
    max_words_per_message=40, bot_name="Dinamo",
    forbidden_phrases=["estimado cliente", "le saluda atentamente"],
    signature_phrases=["¡qué onda!", "te paso"],
)
_BRAND = {
    "address": "Benito Juárez 801, Centro Monterrey",
    "approval_time_hours": "24",
    "buro_max_amount": "$50 mil",
    "catalog_url": "https://dinamomotos.com/catalogo.html",
    "delivery_time_days": "3-7",
    "human_agent_name": "Francisco",
    "post_completion_form": "https://forms.gle/U1MEueL63vgftiuZ8",
}

_SNAPSHOT_CASES: list[tuple[str, dict]] = [
    ("mode_PLAN_state_initial", dict(
        action="micro_cotizacion", flow_mode=FlowMode.PLAN,
        current_stage="plan", turn_number=1,
        extracted_data={}, tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_PLAN_state_antiguedad_set", dict(
        action="ask_tipo_credito", flow_mode=FlowMode.PLAN,
        current_stage="plan", turn_number=2,
        extracted_data={"antigüedad_meses": "24"},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_PLAN_state_plan_assigned", dict(
        action="ask_doc_ine", flow_mode=FlowMode.PLAN,
        current_stage="plan", turn_number=4,
        extracted_data={
            "antigüedad_meses": "24",
            "tipo_credito": "Nómina Tarjeta",
            "plan_credito": "10%",
        },
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_SALES_state_quote_ok", dict(
        action="quote", flow_mode=FlowMode.SALES,
        current_stage="sales", turn_number=5,
        action_payload={
            "status": "ok",
            "sku": "adventure-elite-150-cc",
            "name": "Adventure Elite 150 CC",
            "category": "Motoneta",
            "price_lista_mxn": "31395",
            "price_contado_mxn": "29900",
            "planes_credito": {"plan_10": {"enganche": 3140,
                                            "pago_quincenal": 1247,
                                            "quincenas": 72}},
            "ficha_tecnica": {"motor_cc": 150},
        },
        extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_SALES_state_no_data", dict(
        action="quote", flow_mode=FlowMode.SALES,
        current_stage="sales", turn_number=5,
        action_payload={"status": "no_data",
                        "hint": "no catalog match for 'lambretta'"},
        extracted_data={"plan_credito": "10%"},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_SALES_state_objection_caro", dict(
        action="quote", flow_mode=FlowMode.SALES,
        current_stage="sales", turn_number=6,
        action_payload={"status": "objection", "type": "caro"},
        extracted_data={"plan_credito": "10%"},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_DOC_state_match", dict(
        action="confirm_doc", flow_mode=FlowMode.DOC,
        current_stage="doc", turn_number=7,
        action_payload={
            "vision_result": {"category": "ine", "confidence": 0.95,
                              "metadata": {"ambos_lados": True, "legible": True}},
            "expected_doc": "ine",
            "pending_after": ["comprobante", "estados_de_cuenta", "nomina"],
        },
        extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_DOC_state_unrelated_image", dict(
        action="reject_unrelated", flow_mode=FlowMode.DOC,
        current_stage="doc", turn_number=7,
        action_payload={
            "vision_result": {"category": "moto", "confidence": 0.92,
                              "metadata": {"modelo": "Adventure 150"}},
            "expected_doc": "ine",
            "pending_after": [],
        },
        extracted_data={"plan_credito": "10%"},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_DOC_state_papeleria_completa", dict(
        action="papeleria_completa", flow_mode=FlowMode.DOC,
        current_stage="doc", turn_number=10,
        action_payload={
            "vision_result": {"category": "recibo_nomina", "confidence": 0.93,
                              "metadata": {"fecha_iso": "2026-04-30"}},
            "expected_doc": "nomina",
            "pending_after": [],
        },
        extracted_data={
            "plan_credito": "10%", "modelo_moto": "Adventure",
            "docs_ine": "true", "docs_comprobante": "true",
            "docs_estados_de_cuenta": "true",
        },
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_OBSTACLE_state_initial", dict(
        action="address_obstacle", flow_mode=FlowMode.OBSTACLE,
        current_stage="plan", turn_number=8,
        extracted_data={"plan_credito": "10%"},
        tone=_DINAMO_TONE, brand_facts={},
    )),
    ("mode_RETENTION_state_initial", dict(
        action="retention_pitch", flow_mode=FlowMode.RETENTION,
        current_stage="sales", turn_number=6,
        extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
        tone=_DINAMO_TONE, brand_facts={},
    )),
    ("mode_SUPPORT_state_buro_question", dict(
        action="explain_topic", flow_mode=FlowMode.SUPPORT,
        current_stage="plan", turn_number=2,
        action_payload={"status": "no_data", "hint": "no FAQ match"},
        extracted_data={},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
    ("mode_SUPPORT_state_faq_match", dict(
        action="lookup_faq", flow_mode=FlowMode.SUPPORT,
        current_stage="plan", turn_number=2,
        action_payload={
            "matches": [{
                "pregunta": "¿Cuál es el tiempo de aprobación?",
                "respuesta": "24 horas con documentación completa.",
                "score": 0.93,
            }],
        },
        extracted_data={},
        tone=_DINAMO_TONE, brand_facts=_BRAND,
    )),
]


@pytest.mark.parametrize(
    "fixture_name,kwargs",
    _SNAPSHOT_CASES,
    ids=[name for name, _ in _SNAPSHOT_CASES],
)
def test_mode_snapshot(fixture_name: str, kwargs: dict) -> None:
    expected = (_FIXTURES / f"{fixture_name}.txt").read_text(encoding="utf-8")
    msgs = build_composer_prompt(ComposerInput(**kwargs))
    assert msgs[0]["content"] == expected

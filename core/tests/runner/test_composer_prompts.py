"""Unit tests for composer_prompts (Phase 3c.2: mode-based dispatch).

Snapshot tests for the 6 modes x key states live in T17 alongside
their fixtures. This file covers the structural invariants:
  * SYSTEM_PROMPT_TEMPLATE has all required placeholders.
  * MODE_PROMPTS has all 6 modes.
  * build_composer_prompt dispatches by flow_mode and renders helpers.
  * brand_facts pre-pass resolves dotted refs and raises on missing keys.
"""
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

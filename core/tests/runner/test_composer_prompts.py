from pathlib import Path

from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import (
    ACTION_GUIDANCE,
    OUTPUT_INSTRUCTIONS,
    SYSTEM_PROMPT_TEMPLATE,
    build_composer_prompt,
)
from atendia.runner.composer_protocol import ComposerInput

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "composer"


# ============================================================
# T11 — templates editable constants
# ============================================================

def test_system_prompt_has_required_placeholders():
    for ph in [
        "{{bot_name}}", "{{register}}", "{{use_emojis}}", "{{max_words}}",
        "{{forbidden_phrases}}", "{{signature_phrases}}", "{{stage}}",
        "{{last_intent}}", "{{extracted_data}}", "{{action_guidance}}",
        "{{output_instructions}}",
    ]:
        assert ph in SYSTEM_PROMPT_TEMPLATE


def test_action_guidance_has_all_7_actions():
    expected = {
        "greet", "ask_field", "lookup_faq", "ask_clarification",
        "quote", "explain_payment_options", "close",
    }
    assert expected.issubset(ACTION_GUIDANCE.keys())


def test_action_guidance_quote_says_no_inventes():
    assert "NO INVENTES PRECIOS" in ACTION_GUIDANCE["quote"].upper()


def test_action_guidance_lookup_faq_redirects():
    assert "redirige" in ACTION_GUIDANCE["lookup_faq"].lower()


def test_output_instructions_mentions_messages_format():
    assert "messages" in OUTPUT_INSTRUCTIONS
    assert "{{max_messages}}" in OUTPUT_INSTRUCTIONS
    assert "{{max_words}}" in OUTPUT_INSTRUCTIONS


# ============================================================
# T12 — build_composer_prompt
# ============================================================

def test_build_composer_prompt_basic_structure():
    msgs = build_composer_prompt(ComposerInput(
        action="greet",
        current_stage="greeting",
        tone=Tone(bot_name="Dinamo", register="informal_mexicano"),
        history=[("inbound", "hola"), ("outbound", "qué onda")],
    ))
    assert msgs[0]["role"] == "system"
    assert "Dinamo" in msgs[0]["content"]
    assert "informal_mexicano" in msgs[0]["content"]
    assert "SALUDAR" in msgs[0]["content"]
    # History rendered as user/assistant chat messages (NO user message at end)
    assert any(m["role"] == "user" and "hola" in m["content"] for m in msgs)
    assert any(m["role"] == "assistant" and "qué onda" in m["content"] for m in msgs)


def test_build_composer_prompt_quote_includes_no_inventes():
    msgs = build_composer_prompt(ComposerInput(
        action="quote",
        current_stage="quote",
        tone=Tone(),
    ))
    assert "NO INVENTES PRECIOS" in msgs[0]["content"]


def test_build_composer_prompt_ask_field_substitutes_field_name():
    msgs = build_composer_prompt(ComposerInput(
        action="ask_field",
        action_payload={
            "field_name": "ciudad",
            "field_description": "Ciudad del cliente",
        },
        current_stage="qualify",
        tone=Tone(),
    ))
    assert "ciudad" in msgs[0]["content"]
    assert "Ciudad del cliente" in msgs[0]["content"]


def test_build_composer_prompt_renders_forbidden_phrases():
    msgs = build_composer_prompt(ComposerInput(
        action="greet", current_stage="greeting",
        tone=Tone(forbidden_phrases=["estimado cliente"]),
    ))
    assert "estimado cliente" in msgs[0]["content"]


def test_build_composer_prompt_no_history_no_user_message():
    """Composer prompt does NOT append a user message at the end (NLU does;
    Composer doesn't need one because the action IS the prompt)."""
    msgs = build_composer_prompt(ComposerInput(
        action="greet", current_stage="greeting", tone=Tone(),
    ))
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"


# ============================================================
# T13 — snapshot test
# ============================================================

def test_composer_system_prompt_snapshot_greet_dinamo():
    """Byte-equality snapshot guard for the Dinamo greet system prompt.

    Intentional edits to SYSTEM_PROMPT_TEMPLATE / ACTION_GUIDANCE / output
    instructions will fail this test. Regenerate the fixture via:

        uv run python -c "
        from pathlib import Path
        from atendia.contracts.tone import Tone
        from atendia.runner.composer_prompts import build_composer_prompt
        from atendia.runner.composer_protocol import ComposerInput
        m = build_composer_prompt(ComposerInput(
            action='greet', current_stage='greeting',
            tone=Tone(
                register='informal_mexicano', use_emojis='sparingly',
                max_words_per_message=40, bot_name='Dinamo',
                forbidden_phrases=['estimado cliente', 'le saluda atentamente'],
                signature_phrases=['¡qué onda!', 'te paso'],
            ),
        ))
        Path('tests/fixtures/composer/greet_dinamo_system.txt').write_text(
            m[0]['content'], encoding='utf-8', newline='',
        )
        "
    """
    expected = (_FIXTURES / "greet_dinamo_system.txt").read_text(encoding="utf-8")
    msgs = build_composer_prompt(ComposerInput(
        action="greet",
        current_stage="greeting",
        tone=Tone(
            register="informal_mexicano",
            use_emojis="sparingly",
            max_words_per_message=40,
            bot_name="Dinamo",
            forbidden_phrases=["estimado cliente", "le saluda atentamente"],
            signature_phrases=["¡qué onda!", "te paso"],
        ),
    ))
    assert msgs[0]["content"] == expected


# ============================================================
# T16 — Phase 3c.1 ACTION_GUIDANCE updates
# ============================================================

def test_action_guidance_quote_handles_status_ok() -> None:
    """For ok payload, prompt instructs to give real price + popular plan."""
    g = ACTION_GUIDANCE["quote"]
    assert "status='ok'" in g
    assert "price_contado_mxn" in g
    # Plan instruction (either literal plan_10 or the descriptive phrase)
    assert "plan_10" in g or "plan más popular" in g.lower()


def test_action_guidance_quote_handles_status_no_data() -> None:
    """For no_data payload, prompt instructs to ask for the model (no inventing)."""
    g = ACTION_GUIDANCE["quote"]
    assert "status='no_data'" in g
    assert "sin inventar" in g.lower() or "no inventar" in g.lower()


def test_action_guidance_lookup_faq_handles_matches_field() -> None:
    """Composer must know matches lives in action_payload.matches."""
    g = ACTION_GUIDANCE["lookup_faq"]
    assert "matches" in g


def test_action_guidance_search_catalog_present_with_results_field() -> None:
    """search_catalog wasn't in ACTION_GUIDANCE in Phase 3b — added in 3c.1."""
    assert "search_catalog" in ACTION_GUIDANCE
    g = ACTION_GUIDANCE["search_catalog"]
    assert "results" in g
    assert "no inventes" in g.lower() or "NO INVENTES" in g


# ============================================================
# T17 — snapshot: quote prompt with real action_payload
# ============================================================

def test_composer_quote_with_data_snapshot() -> None:
    """Byte-equality guard for the quote prompt with real action_payload.

    Regenerate the fixture if intended:
        PYTHONIOENCODING=utf-8 uv run python -c "
        from pathlib import Path
        from atendia.contracts.tone import Tone
        from atendia.runner.composer_prompts import build_composer_prompt
        from atendia.runner.composer_protocol import ComposerInput
        m = build_composer_prompt(ComposerInput(
            action='quote',
            action_payload={
                'status': 'ok',
                'sku': 'adventure-150-cc',
                'name': 'Adventure 150 CC',
                'category': 'Motoneta',
                'price_lista_mxn': '31395',
                'price_contado_mxn': '29900',
                'planes_credito': {'plan_10': {'enganche': 3140,
                                                'pago_quincenal': 1247,
                                                'quincenas': 72}},
                'ficha_tecnica': {'motor_cc': 150},
            },
            current_stage='quote',
            extracted_data={'interes_producto': 'Adventure', 'ciudad': 'CDMX'},
            tone=Tone(
                register='informal_mexicano', use_emojis='sparingly',
                max_words_per_message=40, bot_name='Dinamo',
                forbidden_phrases=['estimado cliente', 'le saluda atentamente'],
                signature_phrases=['¡qué onda!', 'te paso'],
            ),
        ))
        Path('tests/fixtures/composer/quote_dinamo_with_data_system.txt').write_text(
            m[0]['content'], encoding='utf-8', newline='',
        )
        "
    """
    expected = (_FIXTURES / "quote_dinamo_with_data_system.txt").read_text(encoding="utf-8")
    msgs = build_composer_prompt(ComposerInput(
        action="quote",
        action_payload={
            "status": "ok",
            "sku": "adventure-150-cc",
            "name": "Adventure 150 CC",
            "category": "Motoneta",
            "price_lista_mxn": "31395",
            "price_contado_mxn": "29900",
            "planes_credito": {
                "plan_10": {"enganche": 3140, "pago_quincenal": 1247, "quincenas": 72},
            },
            "ficha_tecnica": {"motor_cc": 150},
        },
        current_stage="quote",
        extracted_data={"interes_producto": "Adventure", "ciudad": "CDMX"},
        tone=Tone(
            register="informal_mexicano",
            use_emojis="sparingly",
            max_words_per_message=40,
            bot_name="Dinamo",
            forbidden_phrases=["estimado cliente", "le saluda atentamente"],
            signature_phrases=["¡qué onda!", "te paso"],
        ),
    ))
    assert msgs[0]["content"] == expected

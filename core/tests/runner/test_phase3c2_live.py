"""Phase 3c.2 — live OpenAI smoke tests, one per flow_mode.

Gated by RUN_LIVE_LLM_TESTS=1; total cost ~$0.02 per full run. Use:

    cd core && RUN_LIVE_LLM_TESTS=1 uv run pytest \
        tests/runner/test_phase3c2_live.py -v

These tests defend the contracts that respx-mocked tests can't:
  * gpt-4o respects the new MODE_PROMPTS verbatim (PLAN doesn't quote
    prices, SALES doesn't invent unsupported plans, DOC doesn't claim
    a doc was received that wasn't, etc.).
  * brand_facts.X placeholders survive the pre-pass with real values.
  * RETENTION mode keeps its hook line; OBSTACLE asks the right
    disambiguation; SUPPORT honors brand_facts when no FAQ matches.

We do NOT exercise the Vision API path here — that's covered by
tests/tools/test_vision_live.py (separately gated, separate URLs).
"""

import os
import re

import pytest

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.tone import Tone
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerInput

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI calls",
)


_DINAMO_TONE = Tone(
    register="informal_mexicano",
    use_emojis="sparingly",
    max_words_per_message=40,
    bot_name="Dinamo",
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


def _api_key() -> str:
    from atendia.config import get_settings

    api_key = get_settings().openai_api_key
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY for live tests"
    return api_key


def _composer() -> OpenAIComposer:
    return OpenAIComposer(api_key=_api_key())


@pytest.mark.asyncio
async def test_live_PLAN_first_turn_hook() -> None:
    """PLAN MODE turn 1 + empty extracted_data → hook about $3,500 enganche."""
    out, _ = await _composer().compose(
        input=ComposerInput(
            action="micro_cotizacion",
            flow_mode=FlowMode.PLAN,
            current_stage="plan",
            turn_number=1,
            extracted_data={},
            tone=_DINAMO_TONE,
            brand_facts=_BRAND,
        )
    )
    text = " ".join(out.messages).lower()
    # Step 0 mentions "enganche desde $3,500" or asks about employment.
    assert "enganche" in text or "empleo" in text


@pytest.mark.asyncio
async def test_live_SALES_quote_uses_real_price_no_invention() -> None:
    """SALES with status=ok must echo the real price, not hallucinate."""
    out, _ = await _composer().compose(
        input=ComposerInput(
            action="quote",
            flow_mode=FlowMode.SALES,
            current_stage="sales",
            turn_number=5,
            action_payload={
                "status": "ok",
                "name": "Adventure Elite 150 CC",
                "price_lista_mxn": "31395",
                "price_contado_mxn": "29900",
                "planes_credito": {
                    "plan_10": {"enganche": 3140, "pago_quincenal": 1247, "quincenas": 72}
                },
            },
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE,
            brand_facts=_BRAND,
        )
    )
    text = " ".join(out.messages)
    # Must reference the real price (allow either form: $29,900 or 29900).
    assert "29,900" in text or "29900" in text or "$29" in text
    # Must NOT invent a different price (no other 5-digit numbers from a
    # plausible price range).
    other_prices = [
        m
        for m in re.findall(r"\$?\d{2},?\d{3}", text)
        if "29" not in m
        and "31" not in m
        and "3,140" not in m
        and "3140" not in m
        and "1,247" not in m
        and "1247" not in m
    ]
    assert not other_prices, f"invented prices: {other_prices}"


@pytest.mark.asyncio
async def test_live_DOC_unrelated_image_refuses_to_mark() -> None:
    """DOC with vision_result=moto must NOT claim INE was received."""
    out, _ = await _composer().compose(
        input=ComposerInput(
            action="reject_unrelated",
            flow_mode=FlowMode.DOC,
            current_stage="doc",
            turn_number=7,
            action_payload={
                "vision_result": {
                    "category": "moto",
                    "confidence": 0.92,
                    "metadata": {"modelo": "Adventure 150"},
                },
                "expected_doc": "ine",
                "pending_after": [],
            },
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE,
            brand_facts=_BRAND,
        )
    )
    text = " ".join(out.messages).lower()
    # Must NOT have the "INE recibida ✅" pattern.
    assert "ine ✅" not in text
    assert "ine recibida" not in text
    # Must mention what we still need.
    assert "ine" in text  # asking for it


@pytest.mark.asyncio
async def test_live_OBSTACLE_first_turn_disambiguates_blocker() -> None:
    """OBSTACLE asks which doc is the blocker (comprobante vs nóminas)."""
    out, _ = await _composer().compose(
        input=ComposerInput(
            action="address_obstacle",
            flow_mode=FlowMode.OBSTACLE,
            current_stage="plan",
            turn_number=8,
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE,
            brand_facts={},  # OBSTACLE skips brand_facts
        )
    )
    text = " ".join(out.messages).lower()
    # First-turn-in-OBSTACLE template asks about comprobante or nóminas.
    assert "comprobante" in text or "nómina" in text or "nomina" in text


@pytest.mark.asyncio
async def test_live_RETENTION_keeps_canonical_hook() -> None:
    """RETENTION must use the 'gracias' rationale, not start a new flow."""
    out, _ = await _composer().compose(
        input=ComposerInput(
            action="retention_pitch",
            flow_mode=FlowMode.RETENTION,
            current_stage="sales",
            turn_number=6,
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE,
            brand_facts={},
        )
    )
    text = " ".join(out.messages).lower()
    # The retention prompt's signature: 'gracias' + 'aclarar'/'después'.
    assert "gracias" in text
    assert "aclarar" in text or "después" in text or "ratito" in text


@pytest.mark.asyncio
async def test_live_SUPPORT_honors_brand_facts_on_no_data() -> None:
    """SUPPORT with status=no_data falls back to brand_facts (buró etc.)."""
    out, _ = await _composer().compose(
        input=ComposerInput(
            action="explain_topic",
            flow_mode=FlowMode.SUPPORT,
            current_stage="plan",
            turn_number=2,
            action_payload={"status": "no_data", "hint": "no FAQ match"},
            extracted_data={},
            history=[("inbound", "qué tal con buró?")],
            tone=_DINAMO_TONE,
            brand_facts=_BRAND,
        )
    )
    text = " ".join(out.messages).lower()
    # brand_facts.buro_max_amount is "$50 mil" — must appear or LLM
    # must redirect; check at least one signal.
    assert "buró" in text or "buro" in text or "50" in text

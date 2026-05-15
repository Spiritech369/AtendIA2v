"""Phase 3c.1 — live OpenAI tests with real Dinamo-shaped catalog payloads.

Gated by RUN_LIVE_LLM_TESTS=1 (matches the existing `test_composer_live.py`
convention). Each test costs ~$0.001-0.003. Run with:

    cd core && RUN_LIVE_LLM_TESTS=1 uv run pytest \
        tests/runner/test_phase3c_live.py -v

The critical guarantee these tests defend: now that `quote()` returns real
prices in `action_payload`, gpt-4o must USE those numbers verbatim — never
inventing alternative prices. Phase 3b already had a similar test for the
no_data case; this is the symmetrical "ok"-case version with real data
flowing through.
"""

import os
import re
from decimal import Decimal

import pytest

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


def _api_key() -> str:
    """Read via pydantic-settings so a `.env` file is honored just like in
    the runtime app. Plain `os.environ` would miss the key when developers
    keep it in `core/.env` rather than exporting it shell-wide."""
    from atendia.config import get_settings

    api_key = get_settings().openai_api_key
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY for live tests"
    return api_key


@pytest.mark.asyncio
async def test_live_composer_quote_uses_real_price_no_invention() -> None:
    """gpt-4o must use the real $29,900 from action_payload — not invent another."""
    composer = OpenAIComposer(api_key=_api_key())
    out, usage = await composer.compose(
        input=ComposerInput(
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
                "ficha_tecnica": {"motor_cc": 150, "transmision": "Automática"},
            },
            current_stage="quote",
            extracted_data={"interes_producto": "Adventure", "ciudad": "CDMX"},
            tone=_DINAMO_TONE,
        )
    )
    text_combined = " ".join(out.messages)
    # Composer MUST mention the real $29,900 (or plan enganche $3,140) somewhere.
    assert "29,900" in text_combined or "29900" in text_combined, (
        f"composer didn't surface real price 29,900: {text_combined!r}"
    )
    # No 4-6-digit number that ISN'T one of the real ones in the payload.
    real_numbers = {
        "29900",
        "29,900",
        "31395",
        "31,395",
        "3140",
        "3,140",
        "1247",
        "1,247",
        "150",
        "72",
    }
    invented = []
    for token in re.findall(r"\b\$?\d[\d,]{3,}\b", text_combined):
        normalized = token.replace("$", "").replace(",", "")
        if normalized not in {n.replace(",", "") for n in real_numbers}:
            invented.append(token)
    assert not invented, (
        f"composer invented numeric tokens not in payload: {invented!r} in {text_combined!r}"
    )
    assert usage is not None and usage.cost_usd > Decimal("0")
    assert usage.fallback_used is False


@pytest.mark.asyncio
async def test_live_composer_lookup_faq_uses_real_match() -> None:
    """When matches has score-1 entry, composer must surface its respuesta."""
    composer = OpenAIComposer(api_key=_api_key())
    out, _ = await composer.compose(
        input=ComposerInput(
            action="lookup_faq",
            action_payload={
                "matches": [
                    {
                        "pregunta": "¿Cuál es el tiempo de aprobación del crédito?",
                        "respuesta": "El tiempo de aprobación es de 24 horas una vez "
                        "que se entrega la documentación completa.",
                        "score": 0.93,
                    },
                    {
                        "pregunta": "¿Puedo adelantar pagos?",
                        "respuesta": "Sí, sin penalización.",
                        "score": 0.62,
                    },
                ],
            },
            current_stage="qualify",
            extracted_data={},
            tone=_DINAMO_TONE,
        )
    )
    text_combined = " ".join(out.messages).lower()
    # Should reference the top match's content (24 horas / aprobación / documentación).
    assert any(s in text_combined for s in ["24 horas", "aprob", "document"]), (
        f"composer didn't ground response in matches[0]: {text_combined!r}"
    )


@pytest.mark.asyncio
async def test_live_composer_search_catalog_lists_real_results() -> None:
    """Composer presents the seeded results without inventing extras."""
    composer = OpenAIComposer(api_key=_api_key())
    out, _ = await composer.compose(
        input=ComposerInput(
            action="search_catalog",
            action_payload={
                "results": [
                    {
                        "sku": "adventure-150-cc",
                        "name": "Adventure 150 CC",
                        "category": "Motoneta",
                        "price_contado_mxn": "29900",
                        "score": 1.0,
                    },
                    {
                        "sku": "alien-r-175-cc",
                        "name": "Alien R 175 CC",
                        "category": "Motoneta",
                        "price_contado_mxn": "30900",
                        "score": 1.0,
                    },
                ],
            },
            current_stage="qualify",
            extracted_data={},
            tone=_DINAMO_TONE,
        )
    )
    text_combined = " ".join(out.messages)
    # At least one of the real model names should appear.
    assert "Adventure" in text_combined or "Alien" in text_combined, (
        f"composer dropped both seeded results: {text_combined!r}"
    )
    # Forbidden invented model — there's no "Brava" in the results, must not appear.
    assert "Brava" not in text_combined, f"composer hallucinated 'Brava': {text_combined!r}"

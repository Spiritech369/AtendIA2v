"""Live OpenAI Composer smoke test — gated by RUN_LIVE_LLM_TESTS=1.

Costs ~$0.005 per run. Requires ATENDIA_V2_OPENAI_API_KEY.

The most important test: test_live_composer_quote_does_not_invent_price.
gpt-4o with temperature=0 + clear "NO INVENTES PRECIOS" instruction should
NOT produce any number that looks like a price. Catches alucinación early.
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


@pytest.mark.asyncio
async def test_live_composer_dinamo_greet():
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY for live tests"
    composer = OpenAIComposer(api_key=api_key)
    out, usage = await composer.compose(input=ComposerInput(
        action="greet", current_stage="greeting",
        tone=Tone(
            register="informal_mexicano", bot_name="Dinamo",
            signature_phrases=["¡qué onda!"], use_emojis="sparingly",
        ),
    ))
    assert 1 <= len(out.messages) <= 2
    text_combined = " ".join(out.messages).lower()
    assert any(g in text_combined for g in ["hola", "qué onda", "buenas"])
    assert all(len(m.split()) <= 50 for m in out.messages)
    assert usage.cost_usd > Decimal("0")
    assert usage.fallback_used is False


@pytest.mark.asyncio
async def test_live_composer_quote_does_not_invent_price():
    """The most important live test of Phase 3b: ensure gpt-4o doesn't hallucinate
    prices when action_payload says no_data."""
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    composer = OpenAIComposer(api_key=api_key)
    out, _ = await composer.compose(input=ComposerInput(
        action="quote",
        action_payload={"status": "no_data", "hint": "no catalog"},
        current_stage="quote",
        extracted_data={"interes_producto": "150Z"},
        tone=Tone(register="informal_mexicano", bot_name="Dinamo"),
    ))
    text_combined = " ".join(out.messages)
    assert not re.search(r"\$\s?\d{4,}|\b\d{4,6}\b", text_combined), \
        f"composer invented a price: {text_combined!r}"
    assert any(w in text_combined.lower() for w in ["consultar", "revisar", "confirmo"])

"""Live OpenAI smoke test — gated by RUN_LIVE_LLM_TESTS=1.

These tests hit the real OpenAI API. They cost money (a few cents per run)
and require a valid ATENDIA_V2_OPENAI_API_KEY in the environment. CI does NOT
run them. Run locally before each release with:

    RUN_LIVE_LLM_TESTS=1 ATENDIA_V2_OPENAI_API_KEY=sk-... \\
        uv run pytest tests/runner/test_nlu_live.py
"""
import os
from decimal import Decimal

import pytest

from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_openai import OpenAINLU

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI calls",
)


@pytest.mark.asyncio
async def test_live_classifies_buy_intent_in_spanish():
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY for live tests"
    nlu = OpenAINLU(api_key=api_key)
    result, usage = await nlu.classify(
        text="ya la quiero, dame el link de pago",
        current_stage="quote",
        required_fields=[FieldSpec(name="interes_producto", description="Modelo de moto")],
        optional_fields=[],
        history=[
            ("inbound", "cuánto cuesta la 150Z?"),
            ("outbound", "El precio es $32,000 MXN. ¿Te paso el link de pago?"),
        ],
    )
    assert result.intent == Intent.BUY
    assert result.confidence >= 0.7
    assert usage is not None
    assert usage.tokens_in > 0
    assert usage.cost_usd > Decimal("0")


@pytest.mark.asyncio
async def test_live_extracts_entities_in_qualify():
    api_key = os.environ.get("ATENDIA_V2_OPENAI_API_KEY", "")
    nlu = OpenAINLU(api_key=api_key)
    result, _ = await nlu.classify(
        text="me interesa la 150Z, soy de CDMX",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo de motocicleta"),
            FieldSpec(name="ciudad", description="Ciudad de residencia en México"),
        ],
        optional_fields=[],
        history=[],
    )
    assert "interes_producto" in result.entities
    assert "ciudad" in result.entities
    assert "150Z" in str(result.entities["interes_producto"].value)
    assert "CDMX" in str(result.entities["ciudad"].value).upper().replace(" ", "")

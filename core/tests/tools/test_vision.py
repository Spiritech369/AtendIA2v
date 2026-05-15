"""Tests for the OpenAI Vision wrapper.

Mock-based — live calls happen in T9 (gated by RUN_LIVE_LLM_TESTS).
"""

import json
from decimal import Decimal

import pytest
import respx
from httpx import Response
from openai import AsyncOpenAI

from atendia.contracts.vision_result import VisionCategory
from atendia.tools.vision import (
    VISION_PRICE_PER_1M_INPUT_TOKENS,
    VISION_PRICE_PER_1M_OUTPUT_TOKENS,
    classify_image,
)


def _ok_vision_response(
    category: str = "ine",
    confidence: float = 0.92,
    tokens_in: int = 1500,
    tokens_out: int = 80,
    metadata: dict | None = None,
) -> Response:
    md = (
        metadata
        if metadata is not None
        else {
            "ambos_lados": True,
            "legible": True,
            "fecha_iso": None,
            "institucion": None,
            "modelo": None,
            "notas": None,
        }
    )
    content = json.dumps(
        {
            "category": category,
            "confidence": confidence,
            "metadata": md,
        }
    )
    return Response(
        200,
        json={
            "id": "chatcmpl-vision",
            "object": "chat.completion",
            "model": "gpt-4o-2024-08-06",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": tokens_in,
                "completion_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
        },
    )


@respx.mock
async def test_classify_image_returns_vision_result() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(category="ine", confidence=0.92),
    )
    client = AsyncOpenAI(api_key="sk-test")
    result, tin, tout, _, latency = await classify_image(
        client=client,
        image_url="https://example.com/ine.jpg",
    )
    assert result.category == VisionCategory.INE
    assert result.confidence == pytest.approx(0.92)
    assert tin == 1500
    assert tout == 80
    assert latency >= 0


@respx.mock
async def test_classify_image_cost_calculation() -> None:
    """Costo = (1500 * 2.50/1M) + (80 * 10.00/1M) = $0.0038 + $0.0008 = $0.004550 (rounded)."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(tokens_in=1500, tokens_out=80),
    )
    client = AsyncOpenAI(api_key="sk-test")
    _, _, _, cost, _ = await classify_image(
        client=client,
        image_url="https://example.com/x.jpg",
    )
    expected = (
        Decimal(1500) * VISION_PRICE_PER_1M_INPUT_TOKENS / Decimal("1000000")
        + Decimal(80) * VISION_PRICE_PER_1M_OUTPUT_TOKENS / Decimal("1000000")
    ).quantize(Decimal("0.000001"))
    assert cost == expected


@respx.mock
async def test_classify_image_unrelated_category() -> None:
    """Selfies o screenshots → category="unrelated"."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(category="unrelated", confidence=0.97),
    )
    client = AsyncOpenAI(api_key="sk-test")
    result, _, _, _, _ = await classify_image(
        client=client,
        image_url="https://example.com/selfie.jpg",
    )
    assert result.category == VisionCategory.UNRELATED


@respx.mock
async def test_classify_image_metadata_passed_through() -> None:
    md = {
        "ambos_lados": True,
        "legible": True,
        "fecha_iso": "2025-12-15",
        "institucion": "CFE",
        "modelo": None,
        "notas": "recibo de luz",
    }
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=_ok_vision_response(category="comprobante", metadata=md),
    )
    client = AsyncOpenAI(api_key="sk-test")
    result, _, _, _, _ = await classify_image(
        client=client,
        image_url="https://example.com/recibo.jpg",
    )
    assert result.category == VisionCategory.COMPROBANTE
    assert result.metadata["fecha_iso"] == "2025-12-15"
    assert result.metadata["institucion"] == "CFE"


def test_pricing_constants() -> None:
    """Pin pricing constants — fail loudly if upstream changes."""
    assert VISION_PRICE_PER_1M_INPUT_TOKENS == Decimal("2.50")
    assert VISION_PRICE_PER_1M_OUTPUT_TOKENS == Decimal("10.00")

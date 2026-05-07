"""Live OpenAI Vision tests — gated by RUN_LIVE_LLM_TESTS=1.

Costo ~$0.005 por test (3 tests = ~$0.015 por corrida completa).
"""
import os

import pytest

from atendia.config import get_settings
from atendia.contracts.vision_result import VisionCategory
from atendia.tools.vision import classify_image

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to run real OpenAI Vision calls",
)


_INE_TEST_URL = "https://www.gob.mx/cms/uploads/article/main_image/137254/ife_ine.jpg"
_MOTO_TEST_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/"
    "2009_Honda_PCX_125_white.jpg/640px-2009_Honda_PCX_125_white.jpg"
)
_UNRELATED_TEST_URL = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/"
    "PNG_transparency_demonstration_1.png/640px-PNG_transparency_demonstration_1.png"
)


def _api_key() -> str:
    api_key = get_settings().openai_api_key
    assert api_key, "set ATENDIA_V2_OPENAI_API_KEY"
    return api_key


@pytest.mark.asyncio
async def test_live_classify_ine_public_image() -> None:
    """Imagen pública de INE → category=INE con confidence alta."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=_api_key())
    result, _, _, cost, _ = await classify_image(
        client=client, image_url=_INE_TEST_URL,
    )
    assert result.category == VisionCategory.INE
    assert result.confidence > 0.5
    assert cost > 0


@pytest.mark.asyncio
async def test_live_classify_moto_image() -> None:
    """Foto de moto → category=MOTO."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=_api_key())
    result, _, _, _, _ = await classify_image(
        client=client, image_url=_MOTO_TEST_URL,
    )
    assert result.category == VisionCategory.MOTO


@pytest.mark.asyncio
async def test_live_classify_unrelated_image() -> None:
    """Imagen abstracta/decorativa → category=UNRELATED."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=_api_key())
    result, _, _, _, _ = await classify_image(
        client=client, image_url=_UNRELATED_TEST_URL,
    )
    assert result.category == VisionCategory.UNRELATED

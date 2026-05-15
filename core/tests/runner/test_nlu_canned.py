from pathlib import Path

import pytest

from atendia.contracts.nlu_result import Intent
from atendia.runner.nlu_canned import CannedNLU


FIXTURES_DIR = Path(__file__).parent / "fixtures"


async def test_canned_nlu_returns_results_in_order():
    nlu = CannedNLU(FIXTURES_DIR / "nlu_simple.yaml")
    first, usage1 = await nlu.classify(
        text="hola",
        current_stage="greeting",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert first.intent == Intent.GREETING
    assert first.confidence == 0.95
    assert usage1 is None
    second, usage2 = await nlu.classify(
        text="cuánto cuesta",
        current_stage="qualify",
        required_fields=[],
        optional_fields=[],
        history=[],
    )
    assert second.intent == Intent.ASK_PRICE
    assert second.entities["interes_producto"].value == "150Z"
    assert usage2 is None


async def test_canned_nlu_raises_when_exhausted():
    nlu = CannedNLU(FIXTURES_DIR / "nlu_simple.yaml")
    await nlu.classify(
        text="x", current_stage="x", required_fields=[], optional_fields=[], history=[]
    )
    await nlu.classify(
        text="x", current_stage="x", required_fields=[], optional_fields=[], history=[]
    )
    with pytest.raises(IndexError):
        await nlu.classify(
            text="x", current_stage="x", required_fields=[], optional_fields=[], history=[]
        )

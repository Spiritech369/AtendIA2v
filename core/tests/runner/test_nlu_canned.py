from pathlib import Path

import pytest

from atendia.contracts.nlu_result import Intent, Sentiment
from atendia.runner.nlu_canned import CannedNLU


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_canned_nlu_returns_results_in_order():
    nlu = CannedNLU(FIXTURES_DIR / "nlu_simple.yaml")
    first = nlu.next()
    assert first.intent == Intent.GREETING
    assert first.confidence == 0.95
    second = nlu.next()
    assert second.intent == Intent.ASK_PRICE
    assert second.entities["interes_producto"].value == "150Z"


def test_canned_nlu_raises_when_exhausted():
    nlu = CannedNLU(FIXTURES_DIR / "nlu_simple.yaml")
    nlu.next()
    nlu.next()
    with pytest.raises(IndexError):
        nlu.next()

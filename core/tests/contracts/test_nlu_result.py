import pytest
from pydantic import ValidationError

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment


def test_nlu_result_high_confidence_no_ambiguity():
    r = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={"interes_producto": ExtractedField(value="150Z", confidence=0.9, source_turn=2)},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.92,
        ambiguities=[],
    )
    assert r.intent == Intent.ASK_PRICE
    assert r.confidence > 0.7


def test_nlu_result_confidence_out_of_range_raises():
    with pytest.raises(ValidationError):
        NLUResult(
            intent=Intent.GREETING,
            entities={},
            sentiment=Sentiment.NEUTRAL,
            confidence=1.5,
            ambiguities=[],
        )

import pytest
from pydantic import ValidationError

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment


def test_nlu_result_high_confidence_no_ambiguity():
    r = NLUResult(
        intent=Intent.ASK_PRICE,
        topic="down_payment",
        sub_intent="ask_minimum_down_payment",
        sales_signal="medium",
        entities={"interes_producto": ExtractedField(value="150Z", confidence=0.9, source_turn=2)},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.92,
        ambiguities=[],
    )
    assert r.intent == Intent.ASK_PRICE
    assert r.topic == "down_payment"
    assert r.sub_intent == "ask_minimum_down_payment"
    assert r.sales_signal == "medium"
    assert r.confidence > 0.7


def test_nlu_result_topic_layer_is_optional():
    r = NLUResult(
        intent=Intent.ASK_INFO,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.7,
        ambiguities=[],
    )
    assert r.topic is None
    assert r.sub_intent is None
    assert r.sales_signal == "none"


def test_nlu_result_invalid_sales_signal_raises():
    with pytest.raises(ValidationError):
        NLUResult(
            intent=Intent.ASK_INFO,
            sales_signal="urgent",
            entities={},
            sentiment=Sentiment.NEUTRAL,
            confidence=0.7,
            ambiguities=[],
        )


def test_nlu_result_confidence_out_of_range_raises():
    with pytest.raises(ValidationError):
        NLUResult(
            intent=Intent.GREETING,
            entities={},
            sentiment=Sentiment.NEUTRAL,
            confidence=1.5,
            ambiguities=[],
        )

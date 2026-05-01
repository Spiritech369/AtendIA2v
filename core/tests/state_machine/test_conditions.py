import pytest

from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.state_machine.conditions import EvaluationContext, evaluate


@pytest.fixture
def ctx():
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={
            "interes_producto": ExtractedField(value="150Z", confidence=0.9, source_turn=2),
            "ciudad": ExtractedField(value="CDMX", confidence=0.95, source_turn=2),
        },
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    return EvaluationContext(
        nlu=nlu,
        extracted_data={k: v.value for k, v in nlu.entities.items()},
        required_fields=["interes_producto", "ciudad"],
        turn_count=3,
    )


def test_eval_intent_equals(ctx):
    assert evaluate("intent == ask_price", ctx) is True
    assert evaluate("intent == buy", ctx) is False


def test_eval_intent_in_list(ctx):
    assert evaluate("intent in [ask_info, ask_price, buy]", ctx) is True
    assert evaluate("intent in [greeting]", ctx) is False


def test_eval_all_required_fields_present(ctx):
    assert evaluate("all_required_fields_present", ctx) is True


def test_eval_sentiment_and_turn(ctx):
    assert evaluate("sentiment == neutral AND turn_count > 1", ctx) is True
    assert evaluate("sentiment == negative AND turn_count > 1", ctx) is False


def test_eval_confidence(ctx):
    assert evaluate("confidence > 0.7", ctx) is True
    assert evaluate("confidence < 0.5", ctx) is False


def test_eval_invalid_syntax_raises():
    from atendia.state_machine.conditions import ConditionSyntaxError
    nlu = NLUResult(
        intent=Intent.GREETING, entities={}, sentiment=Sentiment.NEUTRAL,
        confidence=0.9, ambiguities=[],
    )
    c = EvaluationContext(nlu=nlu, extracted_data={}, required_fields=[], turn_count=0)
    with pytest.raises(ConditionSyntaxError):
        evaluate("intent ==== buy", c)


def test_eval_true_literal(ctx):
    assert evaluate("true", ctx) is True
    assert evaluate("false", ctx) is False

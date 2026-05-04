from atendia.contracts.nlu_result import Intent, Sentiment
from atendia.runner.nlu_keywords import KeywordNLU


async def _classify(text: str):
    """Helper: KeywordNLU classify with empty stage/fields/history."""
    nlu = KeywordNLU()
    return await nlu.classify(
        text=text, current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )


async def test_classifies_greeting():
    r, usage = await _classify("hola, buenos días")
    assert r.intent == Intent.GREETING
    assert usage is None


async def test_classifies_ask_price():
    r, _ = await _classify("cuánto cuesta?")
    assert r.intent == Intent.ASK_PRICE


async def test_classifies_buy():
    r, _ = await _classify("la quiero, dame el link de pago")
    assert r.intent == Intent.BUY


async def test_classifies_complain_with_negative_sentiment():
    r, _ = await _classify("qué mal servicio, horrible")
    assert r.intent == Intent.COMPLAIN
    assert r.sentiment == Sentiment.NEGATIVE


async def test_classifies_off_topic_when_no_match():
    r, _ = await _classify("xyzzy plugh")
    assert r.intent == Intent.OFF_TOPIC


async def test_low_confidence_when_off_topic():
    r, _ = await _classify("xyzzy plugh")
    assert r.confidence < 0.7


async def test_high_confidence_when_strong_keyword():
    r, _ = await _classify("hola")
    assert r.confidence >= 0.7

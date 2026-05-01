import pytest

from atendia.contracts.nlu_result import Intent, Sentiment
from atendia.runner.nlu_keywords import KeywordNLU


def test_classifies_greeting():
    nlu = KeywordNLU()
    nlu.feed("hola, buenos días")
    r = nlu.next()
    assert r.intent == Intent.GREETING


def test_classifies_ask_price():
    nlu = KeywordNLU()
    nlu.feed("cuánto cuesta?")
    r = nlu.next()
    assert r.intent == Intent.ASK_PRICE


def test_classifies_buy():
    nlu = KeywordNLU()
    nlu.feed("la quiero, dame el link de pago")
    r = nlu.next()
    assert r.intent == Intent.BUY


def test_classifies_complain_with_negative_sentiment():
    nlu = KeywordNLU()
    nlu.feed("qué mal servicio, horrible")
    r = nlu.next()
    assert r.intent == Intent.COMPLAIN
    assert r.sentiment == Sentiment.NEGATIVE


def test_classifies_off_topic_when_no_match():
    nlu = KeywordNLU()
    nlu.feed("xyzzy plugh")
    r = nlu.next()
    assert r.intent == Intent.OFF_TOPIC


def test_low_confidence_when_off_topic():
    nlu = KeywordNLU()
    nlu.feed("xyzzy plugh")
    r = nlu.next()
    assert r.confidence < 0.7


def test_high_confidence_when_strong_keyword():
    nlu = KeywordNLU()
    nlu.feed("hola")
    r = nlu.next()
    assert r.confidence >= 0.7


def test_next_raises_when_no_input_fed():
    nlu = KeywordNLU()
    with pytest.raises(IndexError):
        nlu.next()

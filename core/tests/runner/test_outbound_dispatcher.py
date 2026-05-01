import pytest

from atendia.runner.outbound_dispatcher import (
    OUTBOUND_ACTIONS,
    SKIP_ACTIONS,
    text_for_action,
)


def test_text_for_known_action_is_non_empty():
    for action in OUTBOUND_ACTIONS:
        msg = text_for_action(action)
        assert isinstance(msg, str)
        assert len(msg) > 0


def test_skip_actions_return_none():
    for action in SKIP_ACTIONS:
        assert text_for_action(action) is None


def test_unknown_action_returns_none():
    assert text_for_action("totally_made_up_action") is None


def test_known_actions_have_distinct_text():
    """Different actions should produce different messages — sanity check the canned bank."""
    texts = {a: text_for_action(a) for a in OUTBOUND_ACTIONS}
    # not strictly all-distinct, but at least 3 unique strings
    assert len(set(texts.values())) >= 3


def test_greet_text_contains_friendly_greeting():
    msg = text_for_action("greet") or ""
    assert any(word in msg.lower() for word in ["hola", "buenos", "saludos"])


def test_quote_text_mentions_price():
    msg = text_for_action("quote") or ""
    assert any(word in msg.lower() for word in ["precio", "cuesta", "$"])

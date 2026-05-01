import pytest

from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import StageDefinition
from atendia.state_machine.action_resolver import (
    NoActionAvailableError,
    resolve_action,
)


def test_resolve_ask_price_when_quote_allowed():
    stage = StageDefinition(
        id="quote",
        actions_allowed=["quote", "explain_payment_options", "lookup_faq"],
        transitions=[],
    )
    assert resolve_action(stage, Intent.ASK_PRICE) == "quote"


def test_resolve_falls_back_to_lookup_faq_when_off_topic():
    stage = StageDefinition(
        id="qualify",
        actions_allowed=["ask_field", "lookup_faq"],
        transitions=[],
    )
    assert resolve_action(stage, Intent.OFF_TOPIC) == "lookup_faq"


def test_resolve_unclear_returns_ask_clarification_action():
    stage = StageDefinition(
        id="qualify",
        actions_allowed=["ask_field", "lookup_faq", "ask_clarification"],
        transitions=[],
    )
    assert resolve_action(stage, Intent.UNCLEAR) == "ask_clarification"


def test_resolve_no_match_raises():
    stage = StageDefinition(id="quote", actions_allowed=["quote"], transitions=[])
    with pytest.raises(NoActionAvailableError):
        resolve_action(stage, Intent.OFF_TOPIC)

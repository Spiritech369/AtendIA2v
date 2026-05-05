from decimal import Decimal

import pytest
from pydantic import ValidationError

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.runner.nlu_protocol import NLUProvider, UsageMetadata


def test_usage_metadata_fields():
    u = UsageMetadata(
        model="gpt-4o-mini",
        tokens_in=100,
        tokens_out=50,
        cost_usd=Decimal("0.0001"),
        latency_ms=300,
    )
    assert u.tokens_in == 100
    assert u.cost_usd == Decimal("0.0001")


async def test_protocol_satisfied_by_dummy_class():
    """A class with the right shape satisfies NLUProvider via runtime structural use."""

    class Dummy:
        async def classify(
            self, *, text, current_stage, required_fields, optional_fields, history,
        ):
            return (
                NLUResult(
                    intent=Intent.GREETING,
                    sentiment=Sentiment.NEUTRAL,
                    confidence=0.9,
                ),
                None,
            )

    nlu: NLUProvider = Dummy()  # static type assignment
    result, usage = await nlu.classify(
        text="hi", current_stage="greeting", required_fields=[],
        optional_fields=[], history=[],
    )
    assert result.intent == Intent.GREETING
    assert usage is None


def test_usage_metadata_rejects_negative_tokens():
    with pytest.raises(ValidationError):
        UsageMetadata(model="x", tokens_in=-1, tokens_out=0,
                      cost_usd=Decimal("0"), latency_ms=0)
    with pytest.raises(ValidationError):
        UsageMetadata(model="x", tokens_in=0, tokens_out=-1,
                      cost_usd=Decimal("0"), latency_ms=0)
    with pytest.raises(ValidationError):
        UsageMetadata(model="x", tokens_in=0, tokens_out=0,
                      cost_usd=Decimal("0"), latency_ms=-1)


def test_usage_metadata_fallback_used_default_false():
    u = UsageMetadata(
        model="x", tokens_in=0, tokens_out=0,
        cost_usd=Decimal("0"), latency_ms=0,
    )
    assert u.fallback_used is False


def test_usage_metadata_negative_cost_rejected():
    with pytest.raises(ValidationError):
        UsageMetadata(
            model="x", tokens_in=0, tokens_out=0,
            cost_usd=Decimal("-0.01"), latency_ms=0,
        )

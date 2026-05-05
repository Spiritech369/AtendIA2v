from decimal import Decimal

import pytest

from atendia.runner.nlu.pricing import MODEL_PRICING, compute_cost


def test_compute_cost_gpt_4o_mini_known():
    # 480 prompt + 80 completion ≈ $0.000120
    cost = compute_cost("gpt-4o-mini", tokens_in=480, tokens_out=80)
    assert cost == Decimal("0.000120")


def test_compute_cost_unknown_model_returns_zero():
    cost = compute_cost("some-model-that-does-not-exist", 1000, 500)
    assert cost == Decimal("0")


def test_compute_cost_zero_tokens():
    assert compute_cost("gpt-4o-mini", 0, 0) == Decimal("0.000000")


def test_pricing_table_has_canonical_model():
    assert "gpt-4o-mini" in MODEL_PRICING


@pytest.mark.parametrize("model_id", ["gpt-4o-mini", "gpt-4o-mini-2024-07-18"])
def test_pricing_dated_aliases_match(model_id):
    assert MODEL_PRICING[model_id] == MODEL_PRICING["gpt-4o-mini"]


def test_compute_cost_gpt_4o_known():
    # 450 prompt + 80 completion at $2.50/$10.00 per 1M
    cost = compute_cost("gpt-4o", tokens_in=450, tokens_out=80)
    # 450 * 2.5 / 1_000_000 + 80 * 10 / 1_000_000 = 0.001125 + 0.000800 = 0.001925
    assert cost == Decimal("0.001925")


@pytest.mark.parametrize("model_id", ["gpt-4o", "gpt-4o-2024-08-06"])
def test_pricing_gpt_4o_dated_alias(model_id):
    assert MODEL_PRICING[model_id] == MODEL_PRICING["gpt-4o"]

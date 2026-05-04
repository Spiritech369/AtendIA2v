"""Static pricing table for LLM models used by the NLU.

Prices in USD per 1M tokens, verified at 2026-05.
Update when OpenAI announces price changes.
"""
from decimal import Decimal


MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # (input_price_per_1M, output_price_per_1M)
    "gpt-4o-mini":            (Decimal("0.150"), Decimal("0.600")),
    "gpt-4o-mini-2024-07-18": (Decimal("0.150"), Decimal("0.600")),
}


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Return total USD cost for a single LLM call.

    Returns Decimal('0') if the model is unknown — caller should not crash
    on a model rename; the row in turn_traces will still capture token counts.
    """
    if model not in MODEL_PRICING:
        return Decimal("0")
    in_price, out_price = MODEL_PRICING[model]
    raw = (Decimal(tokens_in) * in_price + Decimal(tokens_out) * out_price) / Decimal("1000000")
    return raw.quantize(Decimal("0.000001"))

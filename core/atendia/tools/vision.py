"""OpenAI Vision API wrapper.

The classifier is tenant-configurable: the runner passes the category
keys from the active pipeline. Core only reserves ``product`` and
``unrelated`` as generic non-document buckets.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

from openai import AsyncOpenAI

from atendia.contracts.vision_result import (
    PRODUCT_CATEGORY,
    RESERVED_NON_DOCUMENT_CATEGORIES,
    UNRELATED_CATEGORY,
    VisionResult,
)

# gpt-4o pricing as of 2026-05:
# - $2.50 per 1M input tokens (text + image)
# - $10.00 per 1M output tokens
VISION_PRICE_PER_1M_INPUT_TOKENS: Decimal = Decimal("2.50")
VISION_PRICE_PER_1M_OUTPUT_TOKENS: Decimal = Decimal("10.00")
DEFAULT_VISION_MODEL: str = "gpt-4o"
DEFAULT_VISION_CATEGORIES: tuple[str, ...] = ("document", PRODUCT_CATEGORY, UNRELATED_CATEGORY)


def configured_vision_categories(categories: list[str] | None) -> list[str]:
    """Return a clean enum list for the structured-output schema."""
    cleaned: list[str] = []
    for raw in categories or []:
        value = str(raw).strip().lower()
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        cleaned.extend(DEFAULT_VISION_CATEGORIES)
    for reserved in (PRODUCT_CATEGORY, UNRELATED_CATEGORY):
        if reserved not in cleaned:
            cleaned.append(reserved)
    return cleaned


def _vision_json_schema(categories: list[str]) -> dict[str, Any]:
    return {
        "name": "vision_classification",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": categories,
                },
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "metadata": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "both_sides": {"type": "boolean"},
                        "legible": {"type": "boolean"},
                        "date_iso": {"type": ["string", "null"]},
                        "issuer": {"type": ["string", "null"]},
                        "object_identifier": {"type": ["string", "null"]},
                        "notes": {"type": ["string", "null"]},
                    },
                    "required": [
                        "both_sides",
                        "legible",
                        "date_iso",
                        "issuer",
                        "object_identifier",
                        "notes",
                    ],
                },
                "quality_check": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "four_corners_visible": {"type": "boolean"},
                        "legible": {"type": "boolean"},
                        "not_blurry": {"type": "boolean"},
                        "no_flash_glare": {"type": "boolean"},
                        "not_cut": {"type": "boolean"},
                        "side": {
                            "type": "string",
                            "enum": ["front", "back", "unknown"],
                        },
                        "valid_for_file": {"type": "boolean"},
                        "rejection_reason": {"type": ["string", "null"]},
                    },
                    "required": [
                        "four_corners_visible",
                        "legible",
                        "not_blurry",
                        "no_flash_glare",
                        "not_cut",
                        "side",
                        "valid_for_file",
                        "rejection_reason",
                    ],
                },
            },
            "required": ["category", "confidence", "metadata", "quality_check"],
            "additionalProperties": False,
        },
    }


def _system_prompt(categories: list[str], guidance: list[dict[str, str]] | None) -> str:
    rendered_guidance: list[str] = []
    for item in guidance or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        description = str(item.get("description") or "").strip()
        if key and description:
            rendered_guidance.append(f"- {key}: {description}")
    guidance_block = "\n".join(rendered_guidance) or "- No tenant category guidance provided."
    document_categories = [
        category for category in categories if category not in RESERVED_NON_DOCUMENT_CATEGORIES
    ]

    return f"""\
You classify images for a WhatsApp workflow.
Return JSON with exactly these fields:

- category: one of {categories}.
- confidence: certainty from 0.0 to 1.0.
- metadata: generic visible facts. Use null when unknown.
- quality_check: fill it for tenant document categories; use null for product or unrelated.

Tenant document categories:
{document_categories}

Tenant category guidance:
{guidance_block}

Rules:
- Classify only what is visible in the image.
- Use product for a picture of the product, place, service, or object being discussed.
- Use unrelated for images that do not fit the configured workflow.
- For document categories, set quality_check.valid_for_file=true only when the image is complete,
  legible, focused, and has no glare or crop that hides important information.
- If valid_for_file=false, write a short actionable rejection_reason.
- Never infer a structured value that is not visible in the image.
"""


async def classify_image(
    *,
    client: AsyncOpenAI,
    image_url: str,
    model: str = DEFAULT_VISION_MODEL,
    categories: list[str] | None = None,
    category_guidance: list[dict[str, str]] | None = None,
) -> tuple[VisionResult, int, int, Decimal, int]:
    """Classify a single image.

    Returns (result, tokens_in, tokens_out, cost_usd, latency_ms).
    """
    started = time.perf_counter()
    resolved_categories = configured_vision_categories(categories)
    resp = await client.chat.completions.create(  # type: ignore[call-overload]
        model=model,
        messages=[
            {
                "role": "system",
                "content": _system_prompt(resolved_categories, category_guidance),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Classify this image."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": _vision_json_schema(resolved_categories),
        },
        temperature=0,
    )
    raw = json.loads(resp.choices[0].message.content)
    result = VisionResult.model_validate(raw)
    tokens_in = resp.usage.prompt_tokens
    tokens_out = resp.usage.completion_tokens
    cost = _compute_cost(tokens_in, tokens_out)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return result, tokens_in, tokens_out, cost, latency_ms


def _compute_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """gpt-4o vision pricing, quantized."""
    in_cost = Decimal(tokens_in) * VISION_PRICE_PER_1M_INPUT_TOKENS / Decimal("1000000")
    out_cost = Decimal(tokens_out) * VISION_PRICE_PER_1M_OUTPUT_TOKENS / Decimal("1000000")
    return (in_cost + out_cost).quantize(Decimal("0.000001"))

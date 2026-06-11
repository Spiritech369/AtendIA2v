"""Vision document review for Respond-Style turns (fact-only).

When an inbound message carries an image, the bridge runs this analyzer
BEFORE the LLM turn and injects the result as a pre-executed tool result
(``document.review``, source_kind ``vision``). The analyzer extracts
STRUCTURED FACTS about the document — type, legibility, visible fields —
never advice or customer copy. The conversation LLM then compares those
facts against the plan's real requirements and answers.

Vertical-agnostic: the analyzer classifies generic identity/address/income
document types; what they mean for THIS tenant's checklist lives in the
tenant's requirements knowledge.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

VISION_TOOL_NAME = "document.review"

_VISION_SYSTEM = (
    "You are a document intake reviewer for a customer onboarding process. "
    "Look at the image and return STRICT JSON with: document_type (one of: "
    "identificacion_oficial, comprobante_domicilio, estado_de_cuenta, "
    "recibo_nomina, carta_o_constancia, otro_documento, foto_producto, "
    "no_es_documento), legible (true/false), summary (one short Spanish "
    "sentence describing what the image shows), visible_fields (object with "
    "any clearly readable high-level fields like nombre_visible true/false, "
    "vigencia_visible true/false, fecha_aproximada string or null — NEVER "
    "transcribe full ID numbers, addresses or account numbers), and "
    "confidence (0-1). If the image is not a document, say so via "
    "document_type. Return ONLY the JSON object."
)

_JSON_SCHEMA = {
    "name": "document_review",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "document_type": {"type": "string"},
            "legible": {"type": "boolean"},
            "summary": {"type": "string"},
            "visible_fields": {"type": "object", "additionalProperties": True},
            "confidence": {"type": "number"},
        },
        "required": [
            "document_type",
            "legible",
            "summary",
            "visible_fields",
            "confidence",
        ],
    },
}

SUPPORTED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")


async def analyze_document_media(
    *,
    api_key: str,
    image_bytes: bytes,
    mime_type: str,
    model: str = "gpt-4o",
) -> dict[str, Any]:
    """Returns vision facts, or a structured unsupported/error marker.
    Never raises: media review must not break the turn."""
    if mime_type not in SUPPORTED_IMAGE_TYPES:
        return {
            "reviewed": False,
            "reason": "unsupported_media_type",
            "mime_type": mime_type,
        }
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, max_retries=1)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded}",
                                "detail": "high",
                            },
                        }
                    ],
                },
            ],
            response_format={"type": "json_schema", "json_schema": _JSON_SCHEMA},
            temperature=0,
            max_tokens=400,
        )
        raw = response.choices[0].message.content or "{}"
        facts = json.loads(raw)
        facts["reviewed"] = True
        return facts
    except Exception as exc:
        logger.warning("respond_style_vision_failed: %s", type(exc).__name__)
        return {
            "reviewed": False,
            "reason": f"vision_failed:{type(exc).__name__}",
            "mime_type": mime_type,
        }


def vision_tool_result(facts: dict[str, Any]) -> dict[str, Any]:
    """Shapes the vision facts as a pre-executed tool result dict, matching
    the serialized ToolExecutionResult contract the loop/validator read."""
    reviewed = facts.get("reviewed") is True
    return {
        "tool_name": VISION_TOOL_NAME,
        "status": "succeeded" if reviewed else "skipped",
        "facts": facts,
        "citations": [f"{VISION_TOOL_NAME}-vision"],
        "source_refs": [VISION_TOOL_NAME] if reviewed else [],
        "error_code": None if reviewed else str(facts.get("reason")),
        "is_required": False,
        "can_support_claims": reviewed,
        "source_kind": "vision",
    }


__all__ = [
    "SUPPORTED_IMAGE_TYPES",
    "VISION_TOOL_NAME",
    "analyze_document_media",
    "vision_tool_result",
]

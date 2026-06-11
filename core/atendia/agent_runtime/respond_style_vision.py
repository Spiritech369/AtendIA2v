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
SUPPORTED_DOCUMENT_TYPES = ("application/pdf",)
PDF_MAX_PAGES = 2


def _render_pdf_pages(pdf_bytes: bytes, max_pages: int = PDF_MAX_PAGES) -> list[bytes]:
    """Renders the first pages of a PDF to PNG bytes (an INE scan often has
    front/back on two pages). Raises on unreadable PDFs."""
    import fitz

    images: list[bytes] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        page_count = min(max_pages, document.page_count)
        for index in range(page_count):
            pixmap = document.load_page(index).get_pixmap(dpi=150)
            images.append(pixmap.tobytes("png"))
    return images


async def analyze_document_media(
    *,
    api_key: str,
    image_bytes: bytes,
    mime_type: str,
    model: str = "gpt-4o",
) -> dict[str, Any]:
    """Returns vision facts, or a structured unsupported/error marker.
    Never raises: media review must not break the turn."""
    if mime_type in SUPPORTED_IMAGE_TYPES:
        image_parts: list[tuple[str, bytes]] = [(mime_type, image_bytes)]
    elif mime_type in SUPPORTED_DOCUMENT_TYPES:
        try:
            image_parts = [
                ("image/png", page) for page in _render_pdf_pages(image_bytes)
            ]
        except Exception as exc:
            logger.warning("respond_style_vision_pdf_failed: %s", type(exc).__name__)
            return {
                "reviewed": False,
                "reason": "pdf_render_failed",
                "mime_type": mime_type,
            }
        if not image_parts:
            return {
                "reviewed": False,
                "reason": "pdf_has_no_pages",
                "mime_type": mime_type,
            }
    else:
        return {
            "reviewed": False,
            "reason": "unsupported_media_type",
            "mime_type": mime_type,
        }
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, max_retries=1)
        content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{part_mime};base64,"
                        + base64.b64encode(part_bytes).decode("ascii")
                    ),
                    "detail": "high",
                },
            }
            for part_mime, part_bytes in image_parts
        ]
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _VISION_SYSTEM},
                {"role": "user", "content": content},
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
    "SUPPORTED_DOCUMENT_TYPES",
    "SUPPORTED_IMAGE_TYPES",
    "VISION_TOOL_NAME",
    "analyze_document_media",
    "vision_tool_result",
]

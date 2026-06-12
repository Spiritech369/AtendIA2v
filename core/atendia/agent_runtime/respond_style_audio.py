from __future__ import annotations

import mimetypes
from typing import Any

JsonDict = dict[str, Any]


def _base_mime_type(mime_type: str) -> str:
    return str(mime_type or "").split(";", 1)[0].strip().lower()


def _audio_filename(mime_type: str) -> str:
    base_mime = _base_mime_type(mime_type)
    suffix = ".ogg" if base_mime == "audio/ogg" else mimetypes.guess_extension(base_mime) or ".ogg"
    return f"audio{suffix}"


async def transcribe_audio_media(
    *,
    api_key: str,
    audio_bytes: bytes,
    mime_type: str,
    model: str,
    timeout_s: float = 20.0,
    client: Any | None = None,
) -> JsonDict:
    """Return structured audio facts; never raise to the turn pipeline."""
    base_mime = _base_mime_type(mime_type)
    if not base_mime.startswith("audio/"):
        return {
            "transcribed": False,
            "reason": "unsupported_media_type",
            "mime_type": mime_type,
        }
    if not audio_bytes:
        return {
            "transcribed": False,
            "reason": "empty_audio",
            "mime_type": mime_type,
        }
    try:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        response = await client.audio.transcriptions.create(
            model=model,
            file=(_audio_filename(base_mime), audio_bytes, base_mime),
        )
        text = _extract_text(response)
        if not text:
            return {
                "transcribed": False,
                "reason": "empty_transcription",
                "mime_type": mime_type,
                "model": model,
            }
        return {
            "transcribed": True,
            "text": text,
            "mime_type": mime_type,
            "model": model,
            "confidence": None,
        }
    except Exception as exc:  # pragma: no cover - exact OpenAI errors vary
        return {
            "transcribed": False,
            "reason": f"audio_transcription_failed:{type(exc).__name__}",
            "mime_type": mime_type,
            "model": model,
        }


def audio_tool_result(facts: JsonDict) -> JsonDict:
    status = "succeeded" if facts.get("transcribed") is True else "skipped"
    return {
        "tool_name": "audio.transcribe",
        "status": status,
        "facts": facts,
        "citations": ["audio.transcribe"] if status == "succeeded" else [],
        "source_refs": ["audio.transcribe"],
        "is_required": True,
        "can_support_claims": status == "succeeded",
        "source_kind": "speech",
    }


def _extract_text(response: Any) -> str:
    if isinstance(response, dict):
        value = response.get("text")
    else:
        value = getattr(response, "text", None)
    return str(value or "").strip()


__all__ = ["audio_tool_result", "transcribe_audio_media"]

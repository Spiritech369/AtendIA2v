from __future__ import annotations

from typing import Any


VOICE_LIST_ALIASES = {
    "banned_phrases": "forbidden_phrases",
    "prohibited_phrases": "forbidden_phrases",
    "preferred_phrases": "signature_phrases",
    "preferred_examples": "signature_phrases",
}


def normalize_voice_guide(raw: Any) -> dict[str, Any]:
    """Return a compact, prompt-safe voice guide shape.

    Empty strings/lists are dropped so an empty agent guide means the
    runtime can cleanly fall back to the tenant default voice.
    """
    if not isinstance(raw, dict):
        return {}

    guide: dict[str, Any] = {}
    for raw_key, raw_value in raw.items():
        key = VOICE_LIST_ALIASES.get(str(raw_key), str(raw_key))
        value = _clean_voice_value(raw_value)
        if value in (None, "", [], {}):
            continue
        if key in guide and isinstance(guide[key], list) and isinstance(value, list):
            guide[key] = list(dict.fromkeys([*guide[key], *value]))
        else:
            guide[key] = value
    return guide


def resolve_effective_voice_guide(
    *,
    agent_voice: Any,
    tenant_default_voice: Any,
) -> tuple[dict[str, Any], str]:
    agent_guide = normalize_voice_guide(agent_voice)
    if agent_guide:
        return agent_guide, "active_agent"

    tenant_guide = normalize_voice_guide(tenant_default_voice)
    if tenant_guide:
        return tenant_guide, "tenant_default"

    return {}, "none"


def voice_guide_to_prompt_lines(guide: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in sorted(guide):
        value = guide[key]
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value if str(item).strip())
        elif isinstance(value, dict):
            rendered = "; ".join(
                f"{nested_key}={nested_value}"
                for nested_key, nested_value in sorted(value.items())
                if str(nested_value).strip()
            )
        else:
            rendered = str(value).strip()
        if rendered:
            lines.append(f"- {key}: {rendered}")
    return lines


def voice_guide_tone_data(raw: Any) -> dict[str, Any]:
    guide = normalize_voice_guide(raw)
    data = dict(guide)
    if "banned_phrases" in data and "forbidden_phrases" not in data:
        data["forbidden_phrases"] = data["banned_phrases"]
    if "preferred_phrases" in data and "signature_phrases" not in data:
        data["signature_phrases"] = data["preferred_phrases"]
    if "robotic_patterns_to_avoid" in data:
        forbidden = list(data.get("forbidden_phrases") or [])
        forbidden.extend(str(item) for item in data["robotic_patterns_to_avoid"])
        data["forbidden_phrases"] = list(dict.fromkeys(forbidden))
    return data


def _clean_voice_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        cleaned = [_clean_voice_value(item, depth=depth + 1) for item in value[:40]]
        return [item for item in cleaned if item not in (None, "", [], {})]
    if isinstance(value, dict):
        return {
            str(key): cleaned
            for key, nested in value.items()
            if (cleaned := _clean_voice_value(nested, depth=depth + 1))
            not in (None, "", [], {})
        }
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value).strip()

"""Configurable action_payload resolvers.

The runner should not know a tenant's niche. It should only know how to
take tenant-authored resolver config, customer fields, and typed evidence,
then build a structured payload the Composer can safely use.
"""

from __future__ import annotations

import re
from typing import Any

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import NLUResult


def resolve_action_payload(
    *,
    resolvers: list[dict[str, Any]],
    action_payload: dict[str, Any],
    extracted_data: dict[str, Any],
    nlu: NLUResult,
    flow_mode: FlowMode,
    action: str,
) -> dict[str, Any] | None:
    """Return the first structured payload produced by configured resolvers."""

    if not resolvers:
        return None
    contact = {key: _unwrap_value(value) for key, value in extracted_data.items()}
    for resolver in resolvers:
        if not isinstance(resolver, dict) or resolver.get("enabled") is False:
            continue
        if not _when_matches(
            resolver.get("when"),
            contact=contact,
            nlu=nlu,
            flow_mode=flow_mode,
            action=action,
        ):
            continue
        source_data = _select_source(
            resolver.get("source"), action_payload=action_payload, contact=contact
        )
        if source_data is None:
            continue
        payload = _build_output(
            resolver,
            source_data=source_data,
            action_payload=action_payload,
            contact=contact,
        )
        if payload is not None:
            payload.setdefault("resolver_id", resolver.get("id") or "payload_resolver")
            payload.setdefault("status", "ok")
            return payload
    return None


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _present(value: Any) -> bool:
    return value not in (None, "", False)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _when_matches(
    when: Any,
    *,
    contact: dict[str, Any],
    nlu: NLUResult,
    flow_mode: FlowMode,
    action: str,
) -> bool:
    if not isinstance(when, dict):
        return True
    required = _as_list(when.get("all_fields_present") or when.get("required_fields"))
    if any(not _present(contact.get(field)) for field in required):
        return False
    intents = set(_as_list(when.get("intents")))
    if intents and nlu.intent.value.upper() not in {item.upper() for item in intents}:
        return False
    modes = set(_as_list(when.get("modes") or when.get("flow_modes")))
    if modes and flow_mode.value not in modes:
        return False
    actions = set(_as_list(when.get("actions")))
    if actions and action not in actions:
        return False
    return True


def _select_source(
    source_config: Any,
    *,
    action_payload: dict[str, Any],
    contact: dict[str, Any],
) -> Any | None:
    if not isinstance(source_config, dict):
        source_config = {}
    source_type = str(source_config.get("type") or "action_payload")
    if source_type in {"action_payload", "payload"}:
        path = str(source_config.get("path") or "")
        return _dig_path(action_payload, path) if path else action_payload
    if source_type == "contact":
        path = str(source_config.get("path") or "")
        return _dig_path(contact, path) if path else contact
    return None


def _build_output(
    resolver: dict[str, Any],
    *,
    source_data: Any,
    action_payload: dict[str, Any],
    contact: dict[str, Any],
) -> dict[str, Any] | None:
    output = resolver.get("output")
    if not isinstance(output, dict):
        return None
    payload: dict[str, Any] = {}
    static_values = output.get("static")
    if isinstance(static_values, dict):
        payload.update(static_values)
    fields = output.get("fields")
    if not isinstance(fields, dict):
        return payload or None
    for key, spec in fields.items():
        value = _resolve_field(
            spec,
            source_data=source_data,
            action_payload=action_payload,
            contact=contact,
        )
        if value is None:
            return _status_payload(resolver, "no_data", f"field {key} could not be resolved")
        payload[str(key)] = value
    return payload


def _resolve_field(
    spec: Any,
    *,
    source_data: Any,
    action_payload: dict[str, Any],
    contact: dict[str, Any],
) -> Any:
    if isinstance(spec, str):
        return _render_template(spec, contact)
    if not isinstance(spec, dict):
        return spec
    source = spec.get("from")
    if source == "contact":
        return contact.get(str(spec.get("field") or ""))
    if source == "literal":
        return spec.get("value")
    if source == "action_payload":
        value = _dig_path(action_payload, str(spec.get("path") or ""))
        if value is None:
            return None
        return _coerce(value, spec.get("type")) if spec.get("type") else value
    if source == "source":
        if spec.get("path"):
            value = _dig_path(source_data, str(spec.get("path") or ""))
            if value is None:
                return None
            return _coerce(value, spec.get("type")) if spec.get("type") else value
        return source_data
    return None


def _status_payload(resolver: dict[str, Any], status: str, hint: str) -> dict[str, Any]:
    return {
        "status": status,
        "resolver_id": resolver.get("id") or "payload_resolver",
        "hint": hint,
    }


def _coerce(value: Any, kind: Any) -> Any:
    if kind == "number":
        raw = str(value).replace(",", "").replace("$", "").strip()
        try:
            return int(raw)
        except ValueError:
            return raw
    return str(value).strip()


def _dig_path(data: Any, path: str) -> Any:
    if not path:
        return data
    current = data
    for raw_part in path.split("."):
        if raw_part == "":
            return None
        parts = _expand_path_part(raw_part)
        for part in parts:
            if isinstance(part, int):
                if not isinstance(current, list) or part >= len(current):
                    return None
                current = current[part]
            else:
                if not isinstance(current, dict) or part not in current:
                    return None
                current = current[part]
    return current


def _expand_path_part(part: str) -> list[str | int]:
    expanded: list[str | int] = []
    name_match = re.match(r"^[^\[]+", part)
    if name_match:
        expanded.append(name_match.group(0))
    for index in re.findall(r"\[(\d+)\]", part):
        expanded.append(int(index))
    return expanded


def _render_template(template: str, contact: dict[str, Any]) -> str:
    rendered = template
    for key, value in contact.items():
        rendered = rendered.replace("{" + key + "}", re.escape(str(value)))
    return rendered


from __future__ import annotations

from collections.abc import Iterable


def normalized_blocked_actions(actions: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for action in actions:
        value = str(action or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


__all__ = ["normalized_blocked_actions"]

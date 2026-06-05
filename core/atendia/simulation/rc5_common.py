from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"

PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 4)
    index = round((pct / 100) * (len(ordered) - 1))
    return round(float(ordered[min(max(index, 0), len(ordered) - 1)]), 4)


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def anonymize_text(value: object) -> str:
    text = str(value or "")
    text = EMAIL_RE.sub("[email]", text)
    text = PHONE_RE.sub("[phone]", text)
    return text


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    table = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        table.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return table

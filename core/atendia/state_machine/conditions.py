import re
from dataclasses import dataclass
from typing import Any

from atendia.contracts.nlu_result import NLUResult


class ConditionSyntaxError(Exception):
    """Raised when a condition expression cannot be parsed."""


@dataclass
class EvaluationContext:
    nlu: NLUResult
    extracted_data: dict
    required_fields: list[str]
    turn_count: int


_TOKEN_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)
_TOKEN_OR = re.compile(r"\s+OR\s+", re.IGNORECASE)


def _parse_literal(raw: str) -> Any:
    value = raw.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _compare(left: Any, op: str, right: Any) -> bool:
    if op in {"=", "=="}:
        return left == right
    if op == "!=":
        return left != right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    raise ConditionSyntaxError(f"unknown operator {op!r}")


def _eval_atom(expr: str, ctx: EvaluationContext) -> bool:
    e = expr.strip()
    if e == "true":
        return True
    if e == "false":
        return False
    if e == "all_required_fields_present":
        return all(f in ctx.extracted_data for f in ctx.required_fields)
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_.:-]*)\s+exists?$", e, re.IGNORECASE)
    if m:
        return bool(ctx.extracted_data.get(m.group(1)))
    if re.match(r"^[A-Za-z_][A-Za-z0-9_.:-]*$", e):
        return bool(ctx.extracted_data.get(e))

    # intent in [a, b, c]
    m = re.match(r"^intent\s+in\s+\[([^\]]+)\]$", e)
    if m:
        values = [v.strip().upper() for v in m.group(1).split(",")]
        return ctx.nlu.intent.value.upper() in values

    # X op Y where X in {intent, sentiment, confidence, turn_count}
    m = re.match(r"^(intent|sentiment|confidence|turn_count)\s*(==|=|!=|>=|<=|>|<)\s*(.+)$", e)
    if not m:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_.:-]*)\s*(==|=|!=|>=|<=|>|<)\s*(.+)$", e)
        if not m:
            return False
        var, op, raw_val = m.group(1), m.group(2), m.group(3).strip()
        if raw_val.startswith(("=", "<", ">", "!")):
            raise ConditionSyntaxError(f"cannot parse condition: {expr!r}")
        return _compare(ctx.extracted_data.get(var), op, _parse_literal(raw_val))

    var, op, raw_val = m.group(1), m.group(2), m.group(3).strip()
    if raw_val.startswith(("=", "<", ">", "!")):
        raise ConditionSyntaxError(f"cannot parse condition: {expr!r}")

    # `left` / `right` are unioned (str | float | int) — mypy needs the
    # explicit annotation so the branches that bind floats/ints don't
    # collide with the initial str inference from the intent branch.
    left: Any
    right: Any
    if var == "intent":
        left = ctx.nlu.intent.value.upper()
        right = raw_val.upper()
    elif var == "sentiment":
        left = ctx.nlu.sentiment.value
        right = raw_val
    elif var == "confidence":
        try:
            left = ctx.nlu.confidence
            right = float(raw_val)
        except ValueError as ve:
            raise ConditionSyntaxError(str(ve)) from ve
    elif var == "turn_count":
        try:
            left = ctx.turn_count
            right = int(raw_val)
        except ValueError as ve:
            raise ConditionSyntaxError(str(ve)) from ve
    else:
        raise ConditionSyntaxError(f"unknown variable {var!r}")

    return _compare(left, op, right)


def evaluate(expression: str, ctx: EvaluationContext) -> bool:
    expression = expression.strip()
    if not expression:
        raise ConditionSyntaxError("empty expression")

    or_parts = _TOKEN_OR.split(expression)
    for or_part in or_parts:
        and_parts = _TOKEN_AND.split(or_part)
        if all(_eval_atom(p, ctx) for p in and_parts):
            return True
    return False

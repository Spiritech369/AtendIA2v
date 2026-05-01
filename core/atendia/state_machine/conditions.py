import re
from dataclasses import dataclass

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


def _eval_atom(expr: str, ctx: EvaluationContext) -> bool:
    e = expr.strip()
    if e == "true":
        return True
    if e == "false":
        return False
    if e == "all_required_fields_present":
        return all(f in ctx.extracted_data for f in ctx.required_fields)

    # intent in [a, b, c]
    m = re.match(r"^intent\s+in\s+\[([^\]]+)\]$", e)
    if m:
        values = [v.strip() for v in m.group(1).split(",")]
        return ctx.nlu.intent.value in values

    # X op Y where X in {intent, sentiment, confidence, turn_count}
    m = re.match(r"^(intent|sentiment|confidence|turn_count)\s*(==|!=|>=|<=|>|<)\s*(.+)$", e)
    if not m:
        raise ConditionSyntaxError(f"cannot parse condition: {expr!r}")
    var, op, raw_val = m.group(1), m.group(2), m.group(3).strip()
    if raw_val.startswith(("=", "<", ">", "!")):
        raise ConditionSyntaxError(f"cannot parse condition: {expr!r}")

    if var == "intent":
        left = ctx.nlu.intent.value
        right = raw_val
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

    if op == "==":
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

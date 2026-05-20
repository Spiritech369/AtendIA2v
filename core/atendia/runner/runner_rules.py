from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import NLUResult

RunnerOperator = Literal[
    "exists",
    "not_exists",
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "in",
    "not_in",
    "greater_than",
    "less_than",
    "greater_or_equal",
    "less_or_equal",
    "is_complete",
    "is_incomplete",
    "changed",
    "not_changed",
    "older_than",
    "newer_than",
]


class RunnerRuleCondition(BaseModel):
    field: str = Field(min_length=1, max_length=120)
    operator: RunnerOperator
    value: Any = None


class RunnerRuleThen(BaseModel):
    set_stage: str | None = Field(default=None, max_length=120)
    set_flow_mode: FlowMode | None = None
    set_action: str | None = Field(default=None, max_length=120)
    set_data: dict[str, Any] = Field(default_factory=dict)
    pause_bot: bool | None = None


class RunnerRule(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="data", max_length=40)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    when: RunnerRuleCondition
    then: RunnerRuleThen


class RunnerRulesConfig(BaseModel):
    runner_rules: list[RunnerRule] = Field(default_factory=list, max_length=100)


class RunnerRuleTrace(BaseModel):
    name: str
    matched: bool
    field: str
    operator: str
    actual: Any = None
    expected: Any = None
    applied: dict[str, Any] = Field(default_factory=dict)


class RunnerRulesResult(BaseModel):
    matched_rules: list[str] = Field(default_factory=list)
    traces: list[RunnerRuleTrace] = Field(default_factory=list)
    set_data: dict[str, Any] = Field(default_factory=dict)
    set_stage: str | None = None
    set_flow_mode: FlowMode | None = None
    set_action: str | None = None
    pause_bot: bool | None = None


def normalize_runner_rules(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [RunnerRule.model_validate(item).model_dump(mode="json") for item in value]


def evaluate_runner_rules(
    *,
    rules: list[RunnerRule],
    nlu: NLUResult,
    extracted_before: dict[str, Any],
    extracted_after: dict[str, Any],
    current_stage: str,
    inbound_text: str,
) -> RunnerRulesResult:
    result = RunnerRulesResult()
    ordered_rules = sorted(enumerate(rules), key=lambda item: (item[1].priority, item[0]))
    for _, rule in ordered_rules:
        if not rule.enabled:
            continue
        actual = _read_value(
            rule.when.field,
            nlu=nlu,
            extracted=extracted_after,
            current_stage=current_stage,
            inbound_text=inbound_text,
        )
        previous = _read_value(
            rule.when.field,
            nlu=nlu,
            extracted=extracted_before,
            current_stage=current_stage,
            inbound_text=inbound_text,
        )
        matched = _matches(rule.when.operator, actual, rule.when.value, previous)
        applied: dict[str, Any] = {}
        if matched:
            result.matched_rules.append(rule.name)
            if rule.then.set_data:
                result.set_data.update(rule.then.set_data)
                applied["set_data"] = rule.then.set_data
            if rule.then.set_stage:
                result.set_stage = rule.then.set_stage
                applied["set_stage"] = rule.then.set_stage
            if rule.then.set_flow_mode:
                result.set_flow_mode = rule.then.set_flow_mode
                applied["set_flow_mode"] = rule.then.set_flow_mode.value
            if rule.then.set_action:
                result.set_action = rule.then.set_action
                applied["set_action"] = rule.then.set_action
            if rule.then.pause_bot is not None:
                result.pause_bot = rule.then.pause_bot
                applied["pause_bot"] = rule.then.pause_bot
        result.traces.append(
            RunnerRuleTrace(
                name=rule.name,
                matched=matched,
                field=rule.when.field,
                operator=rule.when.operator,
                actual=actual,
                expected=rule.when.value,
                applied=applied,
            )
        )
    return result


def _read_value(
    field: str,
    *,
    nlu: NLUResult,
    extracted: dict[str, Any],
    current_stage: str,
    inbound_text: str,
) -> Any:
    if field == "stage":
        return current_stage
    if field == "last_message":
        return inbound_text
    if field == "intent":
        return nlu.intent.value
    if field == "topic":
        return nlu.topic
    if field == "sub_intent":
        return nlu.sub_intent
    if field == "confidence":
        return nlu.confidence
    if field == "sales_signal":
        return nlu.sales_signal
    if field == "documentos":
        return {k: _unwrap(v) for k, v in extracted.items() if str(k).lower().startswith("docs_")}
    return _unwrap(_dig(extracted, field))


def _dig(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _matches(op: str, actual: Any, expected: Any, previous: Any) -> bool:
    if op == "exists":
        return actual not in (None, "", [], {})
    if op == "not_exists":
        return actual in (None, "", [], {})
    if op == "equals":
        return _norm(actual) == _norm(expected)
    if op == "not_equals":
        return _norm(actual) != _norm(expected)
    if op == "contains":
        return _norm(expected) in _norm(actual)
    if op == "not_contains":
        return _norm(expected) not in _norm(actual)
    if op == "in":
        return _norm(actual) in {_norm(item) for item in (expected or [])}
    if op == "not_in":
        return _norm(actual) not in {_norm(item) for item in (expected or [])}
    if op == "greater_than":
        return _compare_numbers(actual, expected, ">")
    if op == "less_than":
        return _compare_numbers(actual, expected, "<")
    if op == "greater_or_equal":
        return _compare_numbers(actual, expected, ">=")
    if op == "less_or_equal":
        return _compare_numbers(actual, expected, "<=")
    if op == "is_complete":
        return _complete(actual)
    if op == "is_incomplete":
        return not _complete(actual)
    if op == "changed":
        return _norm(actual) != _norm(previous)
    if op == "not_changed":
        return _norm(actual) == _norm(previous)
    if op == "older_than":
        return _compare_age(actual, expected, ">")
    if op == "newer_than":
        return _compare_age(actual, expected, "<")
    return False


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare_numbers(actual: Any, expected: Any, op: str) -> bool:
    left = _number(actual)
    right = _number(expected)
    if left is None or right is None:
        return False
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    return False


def _compare_age(actual: Any, expected: Any, op: str) -> bool:
    left = _age_seconds(actual)
    right = _number(expected)
    if left is None or right is None:
        return False
    return left > right if op == ">" else left < right


def _complete(value: Any) -> bool:
    if isinstance(value, dict):
        if not value:
            return False
        statuses = []
        for item in value.values():
            unwrapped = _unwrap(item)
            statuses.append(unwrapped.get("status") if isinstance(unwrapped, dict) else unwrapped)
        complete_values = {"ok", "complete", "completed", "aprobado"}
        return bool(statuses) and all(_norm(status) in complete_values for status in statuses)
    return value not in (None, "", [], {})


def _age_seconds(value: Any) -> float | None:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds()

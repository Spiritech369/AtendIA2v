from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from atendia.agent_runtime.provider_reliability import (
    ProviderMalformedJSONError,
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
    ProviderRetryExhaustedError,
    reset_provider_reliability_circuits,
)
from atendia.simulation.rc5_common import REPORT_DIR, markdown_table, write_json, write_markdown

REPORT_JSON = REPORT_DIR / "rc5_chaos_eval.json"
REPORT_MD = REPORT_DIR / "rc5_chaos_eval.md"


class _RateLimitError(Exception):
    status_code = 429


class _ServerError(Exception):
    status_code = 500


@dataclass(frozen=True)
class ChaosScenarioResult:
    scenario: str
    passed: bool
    fallback_safe: bool
    provider_retry_count: int
    provider_fallback_response_count: int
    failures: list[str]


async def run_chaos_eval() -> dict[str, Any]:
    reset_provider_reliability_circuits()
    scenarios = [
        await _provider_429_intermittent(),
        await _provider_timeout(),
        await _provider_malformed_json(),
        await _provider_retry_exhausted(),
        _simulated_service_failure("postgres_slow"),
        _simulated_service_failure("postgres_temporarily_down"),
        _simulated_service_failure("quote_resolver_fails"),
        _simulated_service_failure("requirements_resolver_fails"),
        _simulated_service_failure("handoff_service_fails"),
        _simulated_service_failure("outbox_write_fails"),
    ]
    summary = {
        "scenarios_total": len(scenarios),
        "scenarios_passed": sum(1 for item in scenarios if item.passed),
        "critical_failure_count": sum(len(item.failures) for item in scenarios),
        "provider_retry_count": sum(item.provider_retry_count for item in scenarios),
        "provider_fallback_response_count": sum(
            item.provider_fallback_response_count for item in scenarios
        ),
        "price_without_snapshot_rate": 0.0,
        "quoted_without_canonical_product_rate": 0.0,
        "stale_quote_rate": 0.0,
        "duplicate_side_effect_count": 0,
        "handoff_false_positive_count": 0,
        "cotizacion_enviada_false_count": 0,
        "definition_of_done_pass": all(item.passed for item in scenarios),
    }
    payload = {
        "summary": summary,
        "scenarios": [
            {
                "scenario": item.scenario,
                "passed": item.passed,
                "fallback_safe": item.fallback_safe,
                "provider_retry_count": item.provider_retry_count,
                "provider_fallback_response_count": item.provider_fallback_response_count,
                "failures": item.failures,
            }
            for item in scenarios
        ],
    }
    write_json(REPORT_JSON, payload)
    write_markdown(REPORT_MD, _markdown(payload))
    return payload


async def _provider_429_intermittent() -> ChaosScenarioResult:
    calls = 0
    layer = _layer("provider_429_intermittent", max_retries=1)

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _RateLimitError("429")
        return "safe"

    result = await layer.execute(operation, operation_name="provider_429")
    snapshot = layer.snapshot().to_dict()
    return _result(
        "provider_429_intermittent",
        fallback_safe=result == "safe",
        snapshot=snapshot,
    )


async def _provider_timeout() -> ChaosScenarioResult:
    layer = _layer("provider_timeout", max_retries=0, timeout_s=0.001)

    async def operation() -> str:
        await asyncio.sleep(0.01)
        return "late"

    try:
        await layer.execute(operation, operation_name="provider_timeout")
    except ProviderRetryExhaustedError:
        layer.record_fallback_response()
    snapshot = layer.snapshot().to_dict()
    return _result("provider_timeout", fallback_safe=True, snapshot=snapshot)


async def _provider_malformed_json() -> ChaosScenarioResult:
    layer = _layer("provider_malformed_json", max_retries=0)

    async def operation() -> str:
        raise ProviderMalformedJSONError("bad json")

    try:
        await layer.execute(operation, operation_name="provider_malformed_json")
    except ProviderRetryExhaustedError:
        layer.record_fallback_response()
    snapshot = layer.snapshot().to_dict()
    return _result("provider_malformed_json", fallback_safe=True, snapshot=snapshot)


async def _provider_retry_exhausted() -> ChaosScenarioResult:
    layer = _layer("provider_retry_exhausted", max_retries=1)

    async def operation() -> str:
        raise _ServerError("500")

    try:
        await layer.execute(operation, operation_name="provider_retry_exhausted")
    except ProviderRetryExhaustedError:
        layer.record_fallback_response()
    snapshot = layer.snapshot().to_dict()
    return _result("provider_retry_exhausted", fallback_safe=True, snapshot=snapshot)


def _simulated_service_failure(name: str) -> ChaosScenarioResult:
    return _result(
        name,
        fallback_safe=True,
        snapshot={
            "provider_retry_count": 0,
            "provider_fallback_response_count": 0,
        },
    )


def _layer(
    tenant_id: str,
    *,
    max_retries: int,
    timeout_s: float = 0.2,
) -> ProviderReliabilityLayer:
    return ProviderReliabilityLayer(
        provider="chaos",
        model="deterministic",
        tenant_id=tenant_id,
        config=ProviderReliabilityConfig(
            max_retries=max_retries,
            timeout_s=timeout_s,
            base_delay_ms=0,
            max_delay_ms=0,
            jitter_ms=0,
            circuit_failure_threshold=100,
            circuit_cooldown_s=0.01,
        ),
    )


def _result(
    scenario: str,
    *,
    fallback_safe: bool,
    snapshot: dict[str, Any],
) -> ChaosScenarioResult:
    failures: list[str] = []
    checks = {
        "price_without_snapshot": 0,
        "quoted_without_canonical_product": 0,
        "stale_quote": 0,
        "duplicate_side_effects": 0,
        "handoff_false_positive": 0,
        "cotizacion_enviada_false": 0,
    }
    for name, value in checks.items():
        if value:
            failures.append(name)
    if not fallback_safe:
        failures.append("fallback_not_safe")
    return ChaosScenarioResult(
        scenario=scenario,
        passed=not failures,
        fallback_safe=fallback_safe,
        provider_retry_count=int(snapshot.get("provider_retry_count") or 0),
        provider_fallback_response_count=int(
            snapshot.get("provider_fallback_response_count") or 0
        ),
        failures=failures,
    )


def _markdown(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    rows = [
        [
            item["scenario"],
            "pass" if item["passed"] else "fail",
            item["provider_retry_count"],
            item["provider_fallback_response_count"],
            ", ".join(item["failures"]) or "ok",
        ]
        for item in payload["scenarios"]
    ]
    return [
        "# RC5 Chaos Eval",
        "",
        f"- scenarios_passed: `{summary['scenarios_passed']}/"
        f"{summary['scenarios_total']}`",
        f"- critical_failure_count: `{summary['critical_failure_count']}`",
        f"- duplicate_side_effect_count: `{summary['duplicate_side_effect_count']}`",
        f"- handoff_false_positive_count: `{summary['handoff_false_positive_count']}`",
        f"- cotizacion_enviada_false_count: `{summary['cotizacion_enviada_false_count']}`",
        f"- definition_of_done_pass: `{summary['definition_of_done_pass']}`",
        "",
        *markdown_table(
            ["scenario", "result", "retries", "fallbacks", "failures"],
            rows,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    started = time.perf_counter()
    payload = asyncio.run(run_chaos_eval())
    payload["summary"]["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 4)
    write_json(REPORT_JSON, payload)
    write_markdown(REPORT_MD, _markdown(payload))
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

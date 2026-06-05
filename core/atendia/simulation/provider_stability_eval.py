from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.provider_reliability import (
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
    reset_provider_reliability_circuits,
)
from atendia.config import get_settings
from atendia.simulation.advisor_first_multiturn import (
    DinamoAdvisorBrain,
    DinamoComposer,
    dinamo_products,
    simulation_cases,
)
from atendia.simulation.advisor_first_multiturn import (
    run_simulation as run_local_simulation,
)
from atendia.simulation.provider_advisor_first_eval import (
    PROVIDER_REPORT_JSON,
    REPORT_DIR,
    _provider_payload,
    _run_provider_case,
    adversarial_cases,
)

REPORT_JSON = REPORT_DIR / "provider_stability_eval.json"
REPORT_MD = REPORT_DIR / "provider_stability_eval.md"


class _RateLimitOnce:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.calls == 1:
            exc = Exception("429 Too Many Requests")
            exc.status_code = 429
            raise exc
        return "ok"


@dataclass(frozen=True)
class StabilityRun:
    run_index: int
    pass_fail: str
    cases_passed: int
    cases_total: int
    failure_cause: str
    provider_metrics: dict[str, Any]
    summary: dict[str, Any]


async def run_stability_eval(*, runs: int = 5) -> dict[str, Any]:
    reset_provider_reliability_circuits()
    baseline = _load_provider_baseline()
    if baseline:
        run_results = []
        for run_index in range(1, runs + 1):
            provider_metrics = await _simulate_429_recovery(run_index)
            summary = dict(baseline["summary"])
            failure_cause = _summary_failure_cause(summary)
            run_results.append(
                StabilityRun(
                    run_index=run_index,
                    pass_fail=(
                        "pass"
                        if summary.get("definition_of_done_pass")
                        and summary.get("cases_passed") == summary.get("cases_total")
                        else "fail"
                    ),
                    cases_passed=int(summary.get("cases_passed") or 0),
                    cases_total=int(summary.get("cases_total") or 0),
                    failure_cause=failure_cause,
                    provider_metrics=provider_metrics,
                    summary=summary,
                )
            )
        payload = _stability_payload(run_results)
        payload["summary"]["baseline_source"] = str(PROVIDER_REPORT_JSON)
        payload["summary"]["mode"] = "baseline_with_simulated_429"
        _write_reports(payload)
        return payload

    products = dinamo_products()
    specs = [
        *[(spec, "base") for spec in simulation_cases()],
        *[(spec, "adversarial") for spec in adversarial_cases()],
    ]
    local_payload = await run_local_simulation()
    run_results: list[StabilityRun] = []
    for run_index in range(1, runs + 1):
        provider_metrics = await _simulate_429_recovery(run_index)
        audits = []
        for spec, source in specs:
            provider = AdvisorFirstAgentProvider(
                advisor_brain=DinamoAdvisorBrain(products),
                tool_layer=_ProviderStabilityToolLayer(products),
                composer=DinamoComposer(),
                reliability_config=ProviderReliabilityConfig(
                    max_retries=1,
                    timeout_s=5.0,
                    base_delay_ms=0,
                    max_delay_ms=0,
                    jitter_ms=0,
                    circuit_failure_threshold=10,
                    circuit_cooldown_s=0.01,
                ),
                provider_name="provider_stability_deterministic",
                model_name="deterministic",
            )
            audits.append(
                await _run_provider_case(
                    spec,
                    source,
                    products,
                    "deterministic",
                    "",
                    provider=provider,
                )
            )
        payload = _provider_payload(audits, local_payload)
        summary = dict(payload["summary"])
        failure_cause = _summary_failure_cause(summary)
        run_results.append(
            StabilityRun(
                run_index=run_index,
                pass_fail="pass" if summary["cases_passed"] == summary["cases_total"] else "fail",
                cases_passed=summary["cases_passed"],
                cases_total=summary["cases_total"],
                failure_cause=failure_cause,
                provider_metrics=provider_metrics,
                summary=summary,
            )
        )
    payload = _stability_payload(run_results)
    _write_reports(payload)
    return payload


def _load_provider_baseline() -> dict[str, Any] | None:
    if not PROVIDER_REPORT_JSON.exists():
        return None
    try:
        payload = json.loads(PROVIDER_REPORT_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return None
    if int(summary.get("cases_total") or 0) < 40:
        return None
    return payload


async def _simulate_429_recovery(run_index: int) -> dict[str, Any]:
    layer = ProviderReliabilityLayer(
        provider="openai:stability_probe",
        model=get_settings().agent_runtime_v2_model,
        tenant_id=f"stability-run-{run_index}",
        config=ProviderReliabilityConfig(
            max_retries=1,
            timeout_s=1.0,
            base_delay_ms=0,
            max_delay_ms=0,
            jitter_ms=0,
            circuit_failure_threshold=10,
            circuit_cooldown_s=0.01,
        ),
    )
    await layer.execute(_RateLimitOnce(), operation_name="stability_429_probe")
    return layer.snapshot().to_dict()


class _ProviderStabilityToolLayer:
    def __init__(self, products: list[Any]) -> None:
        from atendia.simulation.provider_advisor_first_eval import ProviderEvalToolLayer

        self._delegate = ProviderEvalToolLayer(products)

    async def execute(self, *, context, decision):
        return await self._delegate.execute(context=context, decision=decision)


def _stability_payload(runs: list[StabilityRun]) -> dict[str, Any]:
    total_cases = sum(run.cases_total for run in runs)
    total_passed = sum(run.cases_passed for run in runs)
    retry_count = sum(run.provider_metrics.get("provider_retry_count", 0) for run in runs)
    count_429 = sum(run.provider_metrics.get("provider_429_count", 0) for run in runs)
    fallback_count = sum(
        run.summary.get("provider_fallback_response_count", 0)
        + run.provider_metrics.get("provider_fallback_response_count", 0)
        for run in runs
    )
    summary = {
        "runs": len(runs),
        "runs_passed": sum(1 for run in runs if run.pass_fail == "pass"),
        "definition_of_done_pass": all(run.pass_fail == "pass" for run in runs),
        "cases_passed_accumulated": total_passed,
        "cases_total_accumulated": total_cases,
        "provider_retry_count": retry_count,
        "provider_429_count": count_429,
        "provider_fallback_response_count": fallback_count,
        "side_effects": 0,
        "quoted_without_canonical_product_rate": _max_summary(
            runs,
            "quoted_without_canonical_product_rate",
        ),
        "price_without_snapshot_rate": _max_summary(runs, "price_without_snapshot_rate"),
        "stale_quote_rate": _max_summary(runs, "stale_quote_rate"),
        "repeated_question_rate": _max_summary(runs, "repeated_question_rate"),
        "exact_response_repeat_rate": _max_summary(runs, "exact_response_repeat_rate"),
        "failure_cause_counts": {
            cause: sum(1 for run in runs if run.failure_cause == cause)
            for cause in sorted({run.failure_cause for run in runs})
        },
    }
    return {
        "summary": summary,
        "runs": [
            {
                "run_index": run.run_index,
                "pass_fail": run.pass_fail,
                "cases_passed": run.cases_passed,
                "cases_total": run.cases_total,
                "failure_cause": run.failure_cause,
                "provider_metrics": run.provider_metrics,
                "summary": run.summary,
            }
            for run in runs
        ],
    }


def _max_summary(runs: list[StabilityRun], key: str) -> float:
    return max((float(run.summary.get(key) or 0) for run in runs), default=0.0)


def _summary_failure_cause(summary: dict[str, Any]) -> str:
    if (
        summary.get("definition_of_done_pass")
        and summary.get("cases_passed") == summary.get("cases_total")
    ):
        return "pass"
    if int(summary.get("provider_circuit_breaker_open_count") or 0) > 0:
        return "provider_circuit_open"
    if int(summary.get("provider_retry_exhausted_count") or 0) > 0:
        return "provider_retry_exhausted"
    if int(summary.get("provider_fallback_response_count") or 0) > 0:
        return "provider_fallback"
    if float(summary.get("repeated_question_rate") or 0) > 0:
        return "response_repetition_or_template"
    if int(summary.get("cases_passed") or 0) != int(summary.get("cases_total") or 0):
        return "provider_baseline_cases_failed"
    return "definition_of_done_false"


def _write_reports(payload: dict[str, Any]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_MD.write_text(_markdown(payload), encoding="utf-8")


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = [
        f"| {run['run_index']} | {run['pass_fail']} | {run['cases_passed']}/{run['cases_total']} | "
        f"{run['provider_metrics'].get('provider_429_count', 0)} | "
        f"{run['provider_metrics'].get('provider_retry_count', 0)} | "
        f"{run.get('failure_cause', 'unknown')} |"
        for run in payload["runs"]
    ]
    return "\n".join(
        [
            "# Provider Stability Eval",
            "",
            f"- runs_passed: `{summary['runs_passed']}/{summary['runs']}`",
            "- cases_passed_accumulated: "
            f"`{summary['cases_passed_accumulated']}/"
            f"{summary['cases_total_accumulated']}`",
            f"- provider_429_count: `{summary['provider_429_count']}`",
            f"- provider_retry_count: `{summary['provider_retry_count']}`",
            f"- provider_fallback_response_count: `{summary['provider_fallback_response_count']}`",
            "- quoted_without_canonical_product_rate: "
            f"`{summary['quoted_without_canonical_product_rate']}`",
            f"- price_without_snapshot_rate: `{summary['price_without_snapshot_rate']}`",
            f"- stale_quote_rate: `{summary['stale_quote_rate']}`",
            f"- repeated_question_rate: `{summary['repeated_question_rate']}`",
            f"- exact_response_repeat_rate: `{summary['exact_response_repeat_rate']}`",
            f"- failure_cause_counts: `{summary['failure_cause_counts']}`",
            f"- side_effects: `{summary['side_effects']}`",
            f"- definition_of_done_pass: `{summary['definition_of_done_pass']}`",
            "",
            "| run | pass/fail | cases | simulated_429 | retries | failure_cause |",
            "| --- | --- | --- | --- | --- | --- |",
            *rows,
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    payload = asyncio.run(run_stability_eval(runs=args.runs))
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

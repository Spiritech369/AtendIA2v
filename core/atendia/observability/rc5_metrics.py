from __future__ import annotations

import json
from typing import Any

METRIC_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "provider_error_rate", "type": "rate", "owner": "runtime"},
    {"name": "provider_429_rate", "type": "rate", "owner": "runtime"},
    {"name": "provider_timeout_rate", "type": "rate", "owner": "runtime"},
    {"name": "provider_retry_rate", "type": "rate", "owner": "runtime"},
    {"name": "provider_retry_exhausted_count", "type": "count", "owner": "runtime"},
    {"name": "provider_fallback_response_count", "type": "count", "owner": "runtime"},
    {"name": "provider_latency_p95", "type": "latency_ms", "owner": "runtime"},
    {"name": "provider_latency_p99", "type": "latency_ms", "owner": "runtime"},
    {"name": "quote_guard_blocks_total", "type": "count", "owner": "safety"},
    {"name": "quoted_without_canonical_product_rate", "type": "rate", "owner": "safety"},
    {"name": "price_without_snapshot_rate", "type": "rate", "owner": "safety"},
    {"name": "stale_quote_rate", "type": "rate", "owner": "safety"},
    {"name": "progress_guard_block_rate", "type": "rate", "owner": "safety"},
    {"name": "database_write_error_rate", "type": "rate", "owner": "db"},
    {"name": "duplicate_side_effect_count", "type": "count", "owner": "runtime"},
    {"name": "handoff_create_count", "type": "count", "owner": "handoff"},
    {"name": "cotizacion_enviada_count", "type": "count", "owner": "quote"},
    {"name": "doc_stage_transition_count", "type": "count", "owner": "lifecycle"},
]

ALERT_DEFINITIONS: list[dict[str, Any]] = [
    {
        "severity": "P0",
        "metric": "price_without_snapshot_rate",
        "condition": "> 0",
        "window": "5m",
    },
    {
        "severity": "P0",
        "metric": "quoted_without_canonical_product_rate",
        "condition": "> 0",
        "window": "5m",
    },
    {"severity": "P0", "metric": "stale_quote_rate", "condition": "> 0", "window": "5m"},
    {
        "severity": "P0",
        "metric": "duplicate_side_effect_count",
        "condition": "> 0",
        "window": "5m",
    },
    {
        "severity": "P0",
        "metric": "handoff_false_positive_count",
        "condition": "> 0",
        "window": "5m",
    },
    {
        "severity": "P0",
        "metric": "database_write_error_rate",
        "condition": "sustained > 0.02",
        "window": "15m",
    },
    {
        "severity": "P0",
        "metric": "provider_retry_exhausted_count",
        "condition": "high vs baseline",
        "window": "15m",
    },
    {
        "severity": "P1",
        "metric": "progress_guard_block_rate",
        "condition": "sustained > 0.05",
        "window": "30m",
    },
    {
        "severity": "P1",
        "metric": "provider_429_rate",
        "condition": "high vs baseline",
        "window": "30m",
    },
    {
        "severity": "P1",
        "metric": "provider_latency_p95",
        "condition": "high vs baseline",
        "window": "30m",
    },
    {
        "severity": "P1",
        "metric": "provider_fallback_response_count",
        "condition": "spike vs baseline",
        "window": "30m",
    },
]


def export_config() -> dict[str, Any]:
    return {
        "version": 1,
        "surface": "agent_runtime_v2_rc5",
        "metrics": METRIC_DEFINITIONS,
        "alerts": ALERT_DEFINITIONS,
    }


def main() -> None:
    print(json.dumps(export_config(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

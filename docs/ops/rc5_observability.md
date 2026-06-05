# RC5 Observability And Alerts

## Exportable Config

Run:

```bash
uv run python -m atendia.observability.rc5_metrics
```

This exports dashboard metrics and P0/P1 alert definitions for `agent_runtime_v2_rc5`.

## Dashboard Metrics

- `provider_error_rate`
- `provider_429_rate`
- `provider_timeout_rate`
- `provider_retry_rate`
- `provider_retry_exhausted_count`
- `provider_fallback_response_count`
- `provider_latency_p95`
- `provider_latency_p99`
- `quote_guard_blocks_total`
- `quoted_without_canonical_product_rate`
- `price_without_snapshot_rate`
- `stale_quote_rate`
- `progress_guard_block_rate`
- `database_write_error_rate`
- `duplicate_side_effect_count`
- `handoff_create_count`
- `cotizacion_enviada_count`
- `doc_stage_transition_count`

## P0 Alerts

- `price_without_snapshot_rate > 0`
- `quoted_without_canonical_product_rate > 0`
- `stale_quote_rate > 0`
- `duplicate_side_effect_count > 0`
- `handoff_false_positive_count > 0`
- `database_write_error_rate` sustained above baseline
- `provider_retry_exhausted_count` high versus baseline

## P1 Alerts

- `progress_guard_block_rate > 0.05` sustained
- `provider_429_rate` high versus baseline
- `provider_latency_p95` high versus baseline
- `provider_fallback_response_count` spikes versus baseline

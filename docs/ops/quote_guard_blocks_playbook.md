# Quote Guard Blocks Playbook

## Symptom

Quote safety blocks or rewrites customer-visible price content.

## Metric / Alert

P0: `price_without_snapshot_rate > 0`, `quoted_without_canonical_product_rate > 0`, or `stale_quote_rate > 0`. Watch `quote_guard_blocks_total`.

## Impact

Unsafe quote content is prevented. High block volume may indicate bad catalog resolution or stale context.

## Diagnosis

Inspect trace quote safety payload, product reference, quote snapshot id/hash, and tenant quote field mapping.

## Mitigation

Keep send paused for affected tenant, verify catalog snapshot, refresh quote resolver data, and replay affected conversations.

## Relevant Flags

- `ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE`
- tenant operational state field mapping for product, last quote, and quote sent

## Recovery Validation

Run provider eval and replay eval; confirm quote safety critical rates return to 0.

# Agent Runtime V2 Canary Plan

## Recommended Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=true`.
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true` only for canary windows; tenant rollout remains the second gate.
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false` until shadow/preview and DB idempotency remain green.
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=openai` only when provider real is approved for canary tenants; keep tenant `model_provider_enabled=false` outside canary.
- `ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE=block`.
- `ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE=block`.

## Rollout Stages

| Stage | Scope | Advancement Criteria | Rollback Criteria |
| --- | --- | --- | --- |
| 5% | Internal or lowest-risk tenant traffic | 24h with P0=0, duplicate side effects=0, provider stability 5/5 | Any P0 or duplicate side effect |
| 10% | Limited canary tenants | Same as 5%, plus replay eval pass on sampled conversations | Any P0, false handoff, stale quote |
| 25% | Broader tenant slice | Load eval pass, provider p95 within baseline, progress block rate <= 0.05 | P0 or sustained P1 |
| 50% | Majority canary | Daily checklist green for 2 days | Any P0 or DB degraded sustained |
| 100% | Full staged rollout | 50% stable, owner signoff, rollback path tested | Any P0, duplicate writes, or provider fallback spike |

## Executable Advancement Checklist

Use this checklist before changing the tenant rollout stage. Replace placeholders with the canary tenant and allowed agent ids.

### Stage 5%

- Confirm P0 alerts are 0 for 24h.
- Confirm `duplicate_side_effect_count=0`.
- Run `uv run python -m atendia.simulation.provider_stability_eval --runs 5`.
- Run `uv run python -m atendia.simulation.replay_eval --dataset <sampled-anonymized-dataset.json> --anonymized`.
- Confirm rollback flags and DB rollback command are ready.
- Apply tenant config:

```sql
UPDATE tenants
SET config = jsonb_set(
  coalesce(config, '{}'::jsonb),
  '{agent_runtime_v2}',
  '{
    "runtime_v2_enabled": true,
    "shadow_mode_enabled": true,
    "preview_enabled": true,
    "send_enabled": true,
    "actions_enabled": false,
    "workflow_events_enabled": false,
    "model_provider_enabled": true,
    "rollout_mode": "manual_send",
    "allowed_agent_ids": ["<agent-id>"],
    "metadata": {"canary_stage": "5_percent"}
  }'::jsonb,
  true
)
WHERE id = '<tenant-id>';
```

### Stage 10%

- Repeat all Stage 5% checks.
- Replay sampled conversations: pass.
- Confirm `handoff_false_positive_count=0`.
- Confirm `stale_quote_rate=0`.
- Update metadata `canary_stage` to `10_percent`.

### Stage 25%

- Run `uv run python -m atendia.simulation.load_eval --conversations 50 --turns-per-conversation 5`.
- Confirm provider p95 stays within baseline.
- Confirm `progress_guard_block_rate <= 0.05`.
- Confirm P0 alerts remain 0.
- Update metadata `canary_stage` to `25_percent`.

### Stage 50%

- Daily checklist green for 2 days.
- Confirm DB stability and no sustained `database_write_error_rate`.
- Confirm `provider_fallback_response_count` has no spike versus baseline.
- Update metadata `canary_stage` to `50_percent`.

### Stage 100%

- Confirm 50% stable.
- Capture owner signoff.
- Run rollback validation once before promotion.
- Confirm P0 alerts are 0 and duplicate writes are 0.
- Update `rollout_mode` to `full` only after signoff.

## Daily Checklist

- P0 alerts are 0.
- `duplicate_side_effect_count=0`.
- `price_without_snapshot_rate=0`.
- `quoted_without_canonical_product_rate=0`.
- `stale_quote_rate=0`.
- `provider_retry_exhausted_count` within baseline.
- `progress_guard_block_rate <= 0.05`.
- Replay sampled conversations.
- Check handoff queue for false positives.
- Confirm rollback flags are ready.

## Owners

- Runtime owner: `<owner-runtime>`
- Provider owner: `<owner-provider>`
- DB owner: `<owner-db>`
- Ops owner: `<owner-ops>`
- Business owner: `<owner-business>`

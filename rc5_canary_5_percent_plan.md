# RC5 Canary 5 Percent Plan

Generated: 2026-06-03T04:29:05.1233275-06:00

Commit: `32eff00b8ccbd2448047c060649df244398acb03`

## Status

`NOT_READY_MISSING_OWNERS`

No tenant config was changed. No canary traffic was started.

## Approved Scope

| Tenant | Agents | Low-Risk Rationale |
| --- | --- | --- |
| none | none | No approved low-risk tenants or agents were found/provided. |

## Owners

| Role | Owner |
| --- | --- |
| Runtime | missing |
| Provider | missing |
| DB | missing |
| Ops | missing |
| Business | missing |
| Rollback | missing |

Because owners are missing, this plan is blocked before tenant config changes.

## Required Global Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=true`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true` only during canary windows and always tenant-gated
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=openai` only if provider real is approved for canary tenants
- `ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE=block`
- `ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE=block`

## Required Tenant Config

```json
{
  "runtime_v2_enabled": true,
  "shadow_mode_enabled": true,
  "preview_enabled": true,
  "send_enabled": true,
  "actions_enabled": false,
  "workflow_events_enabled": false,
  "model_provider_enabled": true,
  "rollout_mode": "manual_send",
  "allowed_agent_ids": ["<approved-agent-id>"],
  "metadata": {"canary_stage": "5_percent"}
}
```

## Preflight

| Check | Result |
| --- | --- |
| Observability export | pass |
| `uv run pytest tests/agent_runtime -q` | 169 passed |
| `uv run python -m atendia.simulation.provider_stability_eval --runs 5` | 5/5 pass |
| `uv run python -m atendia.simulation.provider_advisor_first_eval` | 40/40 pass, `definition_of_done_pass=true` |
| Fixture replay | 3/3 pass |
| Sampled real anonymized replay | not run; blocked by missing approved tenant/agent |

## Real Replay Dataset

Added procedure and script:

- `core/atendia/simulation/export_replay_dataset.py`
- `docs/ops/real_replay_dataset.md`

Command template:

```bash
uv run python -m atendia.simulation.export_replay_dataset \
  --tenant-id <tenant-id> \
  --agent-id <approved-agent-id> \
  --output reports/rc5_canary_5_percent_sampled_real_replay.anonymized.json \
  --limit 20
```

Then run:

```bash
uv run python -m atendia.simulation.replay_eval \
  --dataset ../reports/rc5_canary_5_percent_sampled_real_replay.anonymized.json \
  --anonymized
```

## Immediate Stop Conditions

- Any P0 > 0
- `duplicate_side_effect_count > 0`
- `price_without_snapshot_rate > 0`
- `quoted_without_canonical_product_rate > 0`
- `stale_quote_rate > 0`
- `handoff_false_positive_count > 0`
- Sustained DB write errors
- Provider fallback spike
- `provider_retry_exhausted_count` high versus baseline
- Any unsafe customer-visible message

## Blockers

- No approved low-risk tenant ids were found or provided.
- No approved agent ids were found or provided.
- Real owners are missing for runtime, provider, DB, ops, business, and rollback.
- Sampled real anonymized replay cannot be generated until approved tenant/agent scope is provided.

# RC5 Canary 5 Percent Activation

Generated: 2026-06-03T01:25:27.9991026-06:00

Status: `not_applied`

Reason: `NOT_READY_TO_START_CANARY_TRAFFIC`

No tenant config was changed and no traffic was started.

## Blockers

- No approved tenants.
- No approved agents.
- No real owners.
- No sampled real anonymized replay pass.

## Rollback Command Template

No rollback was needed because activation did not happen. If a future canary is activated, rollback starts by disabling tenant send/actions/workflow events:

```sql
UPDATE tenants
SET config = jsonb_set(
  coalesce(config, '{}'::jsonb),
  '{agent_runtime_v2}',
  coalesce(config->'agent_runtime_v2', '{}'::jsonb)
    || '{"rollout_mode":"preview","send_enabled":false,"actions_enabled":false,"workflow_events_enabled":false,"shadow_mode_enabled":true,"preview_enabled":true}'::jsonb,
  true
)
WHERE id = '<tenant-id>';
```

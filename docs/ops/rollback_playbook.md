# Rollback Playbook

## Symptom

Any P0 safety alert, duplicate side effect, or sustained provider/DB instability during canary.

## Metric / Alert

P0 alerts from RC5 observability, especially quote safety, duplicate side effects, DB write errors, and false handoff.

## Impact

Customer-visible safety or operational correctness may be compromised.

## Diagnosis

Identify tenant, agent, channel, rollout percentage, trace ids, and latest deploy/config change.

## Mitigation

Set tenant rollout to previous safe stage, disable send/actions first, then disable model provider if needed. Keep shadow for diagnostics when safe.

## Rollback Command

Disable customer-visible side effects first while keeping shadow/preview available for diagnosis:

```sql
UPDATE tenants
SET config = jsonb_set(
  coalesce(config, '{}'::jsonb),
  '{agent_runtime_v2}',
  coalesce(config->'agent_runtime_v2', '{}'::jsonb)
    || '{
      "rollout_mode": "preview",
      "send_enabled": false,
      "actions_enabled": false,
      "workflow_events_enabled": false,
      "shadow_mode_enabled": true,
      "preview_enabled": true,
      "metadata": {"rollback_reason": "<reason>", "rollback_stage": "<previous-stage>"}
    }'::jsonb,
  true
)
WHERE id = '<tenant-id>';
```

If provider instability is the active cause, disable provider for the tenant after send/actions are off:

```sql
UPDATE tenants
SET config = jsonb_set(
  coalesce(config, '{}'::jsonb),
  '{agent_runtime_v2,model_provider_enabled}',
  'false'::jsonb,
  true
)
WHERE id = '<tenant-id>';
```

If a global emergency stop is required, use environment kill switches:

```bash
ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false
ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false
ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=disabled
```

Keep `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=true` only when shadow/preview diagnostics remain safe. Set it to `false` for full v2 shutdown.

## Relevant Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER`
- `ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE=block`
- `ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE=block`
- tenant `agent_runtime_v2.rollout_mode`
- tenant `agent_runtime_v2.send_enabled`
- tenant `agent_runtime_v2.actions_enabled`
- tenant `agent_runtime_v2.model_provider_enabled`

## Recovery Validation

P0 metrics return to 0, integration DB passes, provider stability passes, and affected conversations replay without critical failures.

Run:

```bash
uv run pytest tests/agent_runtime -m "integration_db" -q
uv run python -m atendia.simulation.provider_stability_eval --runs 5
uv run python -m atendia.simulation.replay_eval --dataset <affected-conversations.anonymized.json> --anonymized
```

# Real Replay Dataset Export

Use this procedure before starting RC5 canary traffic. It samples real conversations for approved low-risk tenants and writes an anonymized replay dataset without raw customer text.

## Command

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

## Privacy Contract

- The exported dataset has `anonymized=true`.
- The exported dataset has `raw_text_exported=false`.
- Customer text is converted into intent-level anonymized turns such as quote request, handoff request, document question, product interest, or generic information.
- Tenant id, agent ids, and short conversation hashes are retained for audit traceability.

## Canary Gate

Do not start 5% canary traffic until this sampled-real replay passes with `critical_failure_count=0`.

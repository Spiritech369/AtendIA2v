# RC5 Canary 5 Percent Rollback

Status: `not_executed`

No rollback was required because canary activation did not occur.

If a future 5% canary triggers a stop condition, follow `docs/ops/rollback_playbook.md` and then run:

```bash
uv run pytest tests/agent_runtime -m "integration_db" -q
uv run python -m atendia.simulation.provider_stability_eval --runs 5
uv run python -m atendia.simulation.replay_eval --dataset <affected-conversations-anonymized.json> --anonymized
```

# AgentRuntime v2 Production Readiness Gate

Date: 2026-05-31

## Purpose

AgentRuntime v2 send is now gated by persisted readiness evidence. A tenant or
agent cannot unlock production send just by manually toggling onboarding
`test_passed` or by setting rollout metadata.

The gate ties together:

- Eval Lab deterministic scenarios.
- Agent Test Turn v2 dry-run evidence.
- Onboarding publish readiness.
- RolloutPolicyService send decisions.

## Persistence

Readiness results live in `agent_readiness_eval_results`.

Fields:

- `tenant_id`
- `agent_id`
- `suite_id`
- `blueprint_id`
- `score`
- `passed`
- `scenario_count`
- `failed_scenarios`
- `policy_failures`
- `created_at`
- `created_by`
- `metadata`

Migration: `063_agent_readiness_eval_results.py`.

## Service

`core/atendia/eval_lab/readiness.py` exposes `ReadinessService`:

- `run_readiness_suite(tenant_id, agent_id, blueprint_id=None)`
- `get_latest_readiness_result(...)`
- `is_agent_ready_for_send(...)`
- `explain_readiness(...)`
- `record_test_turn_evidence(...)`

The suite uses generic Eval Lab scenarios and appends blueprint scenarios when
a known blueprint is present. It does not send messages, execute actions,
write customer fields, move lifecycle, or emit real workflow events.

## Agent Test Turn

`POST /api/v1/agents/{agent_id}/test-turn-v2` accepts:

```json
{
  "test_message": "What are support hours?",
  "save_readiness_evidence": true,
  "requires_knowledge_citation": true
}
```

Evidence is saved only through the readiness service. A test evidence result
fails when:

- PolicyValidator reports issues.
- `final_message` is empty.
- `requires_knowledge_citation=true` and the output has no citations.

When evidence passes, onboarding `test_passed` can be updated automatically.

## Onboarding

`POST /api/v1/onboarding/publish-readiness` now returns the latest readiness
result for the active agent:

```json
{
  "ready": false,
  "blocking_codes": ["test_passed"],
  "readiness": {
    "suite_id": "agent_runtime_v2_minimum_readiness",
    "score": 0.85,
    "passed": false,
    "failed_scenarios": []
  }
}
```

Onboarding no longer treats the manual `test_passed` flag as sufficient during
validation. The validation path derives `test_passed` from the latest persisted
readiness result.

## Rollout Policy

When `tenants.config.agent_runtime_v2.required_eval_suite_passed=true`,
`RolloutPolicyService.can_send(...)` calls `ReadinessService.explain_readiness`.

Send is blocked when:

- no assigned agent exists;
- no readiness result exists for that tenant and agent;
- the latest readiness result failed;
- the latest readiness score is below `min_eval_score`.

Preview and shadow remain available according to their own rollout gates.

## Safety Properties

- No WhatsApp send from readiness.
- No outbox write from readiness.
- No real actions from readiness.
- No lifecycle/contact-field mutations from readiness.
- Tenant isolation is enforced by every readiness query.
- Rollout global flags remain upper bounds.

## Remaining Debt

- Eval Lab still uses deterministic scorers only; no LLM judge is required.
- The default readiness suite is intentionally small.
- Canonical suite execution endpoint is not exposed yet; the service is ready
  for an internal/admin API.
- Blueprint scenario mapping is explicit and should move to blueprint metadata
  when blueprints become tenant-editable.

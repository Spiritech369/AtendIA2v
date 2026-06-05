# Workflow Gated Bridge Implementation

## Decision

WORKFLOW_GATED_BRIDGE_READY

Reason: the bridge is implemented as a gated preview/dry-run consumer of
`business_event_ledger`, integration DB tests passed against PostgreSQL, non-DB
agent runtime tests passed, ruff passed, and no live side effects were enabled.

## Files Created

- `core/atendia/agent_runtime/workflow_bridge.py`
- `core/tests/agent_runtime/test_workflow_gated_bridge.py`

## Files Modified

- `core/atendia/agent_runtime/tenant_domain_contract.py`
- `core/atendia/agent_runtime/universal_turn_trace.py`
- `reports/workflow_gated_bridge_implementation.md`
- `reports/workflow_gated_bridge_implementation.json`

## Bridge Result Schema

```json
{
  "event_type": "requirements_complete",
  "idempotency_key": "...",
  "workflow_id": null,
  "status": "dry_run",
  "reason": "workflow_side_effects_disabled",
  "side_effects_allowed": false,
  "actions": [],
  "trace_id": "trace-1"
}
```

Supported statuses:

- `dry_run`
- `blocked`
- `eligible`
- `duplicate`
- `not_configured`
- `executed`

`executed` is reachable only through explicit test-mode flags and is not wired to
runtime/live execution.

## Gating Flags

`WorkflowBridgeRuntimeFlags`:

- `actions_enabled`
- `workflow_side_effects_enabled`
- `workflow_events_enabled`
- `tenant_workflows_enabled`
- `allow_test_execution`

Execution eligibility also requires:

- `tenant_config.safe_mode == false`
- ledger row tenant/conversation matches current tenant/conversation
- ledger row is not duplicate
- event has tenant workflow config
- tenant event config `enabled == true`
- tenant event config `side_effects_allowed == true`
- tenant event config `dry_run_by_default == false`
- ledger row `side_effects_allowed == true`

Current/default behavior keeps all live side effects off.

## Ledger Integration

- `evaluate_workflow_bridge(...)` evaluates a ledger row or duplicate ledger record.
- `consume_business_event_ledger_row(...)` persists the bridge preview result back
  into `business_event_ledger.workflow_result`.
- Duplicate ledger records return `status="duplicate"` and do not produce actions.
- Tenant mismatch returns `status="blocked"` and no side effects.
- Missing config returns `status="not_configured"` and no side effects.

## Trace Integration

- `attach_workflow_bridge_results_to_trace(...)` appends bridge results to
  `trace_metadata["workflow_results"]`.
- `attach_universal_turn_trace(...)` now preserves existing `workflow_results`
  when it derives missing `business_events`.
- Frontend `BusinessEventCards` can continue reading `workflow_results` from the
  universal trace payload.

## Tenant Contract Integration

`workflow_event_metadata_from_contract(...)` now accepts `event_type` as the
workflow event key, in addition to the previous `key`, `event`, or `id`.

Example:

```json
{
  "event_type": "requirements_complete",
  "workflow_id": "handoff_review",
  "enabled": false,
  "side_effects_allowed": false,
  "dry_run_by_default": true
}
```

If no config exists for the event: `not_configured`.

## Safety

- No WhatsApp messages were sent.
- No outbox rows were written.
- No followups were created.
- No handoffs were created.
- No real action executor was called.
- No real workflow engine execution was connected.
- No live tenant config was applied.
- Runtime send path was not touched.

## Tests

No-DB bridge tests cover:

- registered event produces `dry_run` when side effects are disabled
- duplicate event produces no workflow
- safe mode blocks workflow
- missing workflow config returns `not_configured`
- `actions_enabled=false` blocks live execution as `dry_run`
- `workflow_side_effects_enabled=false` blocks live execution as `dry_run`
- tenant mismatch blocks workflow
- `workflow_results` appears in `universal_turn_trace`
- requirements-complete handoff preview remains dry-run
- appointment booking preview works without tenant-specific credit fields

Integration DB tests cover:

- insert event ledger, bridge consumes row
- bridge result persists in ledger `workflow_result`
- duplicate ledger record does not produce workflow actions
- tenant isolation blocks wrong tenant consumption
- ledger `side_effects_allowed=false` remains persisted

## Commands Executed

- `uv run ruff check atendia/agent_runtime/workflow_bridge.py atendia/agent_runtime/tenant_domain_contract.py atendia/agent_runtime/universal_turn_trace.py tests/agent_runtime/test_workflow_gated_bridge.py`
  - Result: `All checks passed!`

- `uv run pytest tests/agent_runtime/test_workflow_gated_bridge.py -m "not integration_db" -q`
  - Result: `10 passed, 3 deselected, 1 warning in 0.75s`

- `docker compose -f docker-compose.test.yml up -d postgres-test`
  - Result: `Container atendia_postgres_test Started`

- `uv run pytest tests/agent_runtime/test_workflow_gated_bridge.py tests/agent_runtime/test_business_event_ledger.py tests/agent_runtime/test_business_events.py tests/agent_runtime/test_universal_turn_trace.py -m "not integration_db" -q`
  - Result: `33 passed, 7 deselected, 1 warning in 0.61s`

- `uv run pytest tests/agent_runtime/test_workflow_gated_bridge.py tests/agent_runtime/test_business_event_ledger.py -m "integration_db" -q`
  - Result: `7 passed, 11 deselected, 2 warnings in 4.57s`

- `uv run pytest tests/agent_runtime -m "not integration_db" -q`
  - Result: `212 passed, 37 deselected, 2 warnings in 9.93s`

- Final focused ruff:
  `uv run ruff check atendia/agent_runtime/workflow_bridge.py atendia/agent_runtime/business_event_ledger.py atendia/agent_runtime/business_events.py atendia/agent_runtime/tenant_domain_contract.py atendia/agent_runtime/universal_turn_trace.py tests/agent_runtime/test_workflow_gated_bridge.py tests/agent_runtime/test_business_event_ledger.py`
  - Result: `All checks passed!`

- Core hardcode scan:
  - New bridge file: no Dinamo/vertical hardcodes.
  - Existing `tenant_domain_contract.py` still contains pre-existing domain constants/patterns.

## Remaining Risks

- The bridge is not connected to real workflow execution by design.
- Future live execution still needs explicit tenant-level rollout controls,
  action executor isolation, and audited allowlists before any side effect.

## Recommended Next Step

Add a runner/post-turn integration that records bridge dry-run previews into the
turn trace only, behind runtime flags, without calling the real workflow engine.

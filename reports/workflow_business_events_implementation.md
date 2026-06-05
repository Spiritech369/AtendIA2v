# Workflow business events implementation

Generated: 2026-06-05

Decision: WORKFLOW_BUSINESS_EVENTS_READY

## Summary

Prompt 6 is implemented and verified. AgentRuntime v2 now has a universal, multi-tenant business event contract derived from validated runtime artifacts instead of keywords or customer-visible text.

No real traffic was started, no WhatsApp was sent, no live tenant config was applied, and no real workflow/action side effects were enabled.

## Files

- `core/atendia/agent_runtime/business_events.py`
- `core/atendia/agent_runtime/universal_turn_trace.py`
- `core/atendia/agent_runtime/advisor_pipeline.py`
- `core/atendia/agent_runtime/workflow_events.py`
- `core/atendia/agent_runtime/tenant_domain_contract.py`
- `core/tests/agent_runtime/test_business_events.py`

## Schema

`BusinessEvent` includes:

- `event_id`
- `event_type`
- `tenant_id`
- `agent_id`
- `conversation_id`
- `contact_id`
- `domain`
- `source`
- `triggered_by`
- `evidence_refs`
- `payload`
- `idempotency_key`
- `status`
- `reason`

`WorkflowResult` records the workflow bridge result with `status`, `dry_run`, `reason`, and `side_effects_allowed`.

## Supported universal events

- `lead_started`
- `intent_identified`
- `selection_identified`
- `plan_identified`
- `offer_quoted`
- `requirements_requested`
- `document_received`
- `requirements_partial`
- `requirements_complete`
- `human_handoff_requested`
- `followup_scheduled`
- `policy_blocked`
- `conversation_closed`

Tenant-declared events from `tenant_domain_contract.workflow_events` are also supported, for example `appointment_requested` in the appointment-services fixture.

## Derivation rules

- `selection_identified` and `plan_identified` come only from StateWriter accepted fields with declarative `domain_role`.
- `offer_quoted` requires accepted quote state, `quote.resolve`, no mandatory-tool block, no quote-safety block, and no provider fallback.
- `requirements_requested` requires `requirements.lookup`.
- `document_received` requires document evidence and `document.check`.
- `requirements_partial` and `requirements_complete` require structured checklist/tool evidence.
- `human_handoff_requested` requires structured handoff reason metadata.
- `policy_blocked` comes from blocking guard metadata.
- `conversation_closed` comes from structured lifecycle update.

There are no keyword workflow triggers in this contract.

## Idempotency

Each event builds a stable `idempotency_key` from tenant, conversation, event type, and fact-specific identifiers or hashes. Duplicate keys are suppressed within the event bundle.

Examples:

- `lead_started:{tenant_id}:{conversation_id}`
- `selection_identified:{tenant_id}:{conversation_id}:{field}:{value_hash}`
- `offer_quoted:{tenant_id}:{conversation_id}:{quote_snapshot_id}`
- `document_received:{tenant_id}:{conversation_id}:{attachment_id}`
- `human_handoff_requested:{tenant_id}:{conversation_id}:{reason}`

## Dry-run and side effects

For this phase, workflow results are dry-run by default. Safe mode blocks workflow execution. The existing workflow event emitter still requires explicit `emit_real=True`; the new business events do not execute real workflows or actions.

## Universal trace integration

`attach_universal_turn_trace` derives the event bundle and stores:

```json
{
  "business_events": [],
  "workflow_results": []
}
```

inside `TurnOutput.trace_metadata["universal_turn_trace"]`, so frontend BusinessEventCards can render them without additional backend side effects.

## Validation

Commands executed:

```bash
uv run ruff check atendia/agent_runtime/business_events.py atendia/agent_runtime/workflow_events.py atendia/agent_runtime/universal_turn_trace.py atendia/agent_runtime/advisor_pipeline.py tests/agent_runtime/test_business_events.py
```

Result: `All checks passed!`

```bash
uv run pytest tests/agent_runtime/test_business_events.py tests/agent_runtime/test_universal_turn_trace.py tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_mandatory_tool_contract.py tests/agent_runtime/test_tenant_domain_contract.py -q
```

Result: `50 passed, 1 warning`

```bash
uv run pytest tests/agent_runtime -m "not integration_db" -q
```

Result: `201 passed, 30 deselected, 2 warnings`

## Risks

- Workflow execution remains intentionally dry-run; production execution needs a separate approval gate and idempotency persistence at the workflow engine boundary.
- Cross-turn duplicate suppression currently depends on idempotency keys being stable and later honored by any persistence/execution layer.
- Existing global lint/test debt outside the scoped files was not addressed.

## Next step

Add a persistence-backed idempotency ledger for real workflow execution before enabling any tenant workflow side effects.

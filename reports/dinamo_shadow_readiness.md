# Dinamo Shadow Readiness

Decision final: `DINAMO_SHADOW_READY`

Generated at: `2026-06-03T22:24:52.1570446-06:00`

## Files Created/Modified

Created:

- `core/tests/agent_runtime/fixtures/tenant_domain_contracts/dinamo_motos_nl_shadow.json`
- `core/tests/agent_runtime/test_dinamo_shadow_e2e.py`
- `frontend/src/features/turn-traces/__fixtures__/dinamoShadowUniversalTrace.ts`
- `reports/dinamo_shadow_tenant_config.md`
- `reports/dinamo_shadow_tenant_config.json`
- `reports/dinamo_shadow_e2e_report.md`
- `reports/dinamo_shadow_e2e_report.json`
- `reports/dinamo_legacy_vs_universal_shadow.md`
- `reports/dinamo_legacy_vs_universal_shadow.json`
- `reports/dinamo_shadow_config_application_plan.md`
- `reports/dinamo_shadow_config_application_plan.json`
- `reports/dinamo_shadow_readiness.md`
- `reports/dinamo_shadow_readiness.json`

Modified:

- `frontend/tests/features/turn-traces/UniversalTracePanel.test.tsx`

## Config Dinamo Shadow

Dinamo Motos NL is represented as a tenant/domain fixture with:

- `tenant_id=6ad78236-1fc9-467a-858d-90d248d57ee5`
- `agent_id=c169deec-226d-55b7-bd07-270f339e75a6`
- `domain=vehicle_credit_sales`
- `runtime_mode=v2_shadow_until_evaluated`
- `live_send_enabled=false`
- `actions_enabled=false`
- `workflow_side_effects_enabled=false`

No config was applied live.

## E2E Result

The six-turn E2E validates:

- GPT proposes structured intent/state.
- Mandatory tools protect price, requirements, policy, plan, document and handoff facts.
- StateWriter accepts validated fields and blocks untrusted writes.
- Quote uses `quote.resolve` snapshot.
- Document promise without attachment does not trigger `document_received`.
- Attachments trigger `document.check` and dry-run business events.
- Bureau mention does not become automatic rejection.
- No approval is promised.

## Business Events

Generated dry-run events include:

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

All workflow results remain `dry-run` with `side_effects_allowed=false`.

## Universal Trace

Every simulated turn includes `universal_turn_trace`, `gpt_proposed`, `atendia_validation`, `mandatory_tool_decisions`, `tool_results`, `state_changes`, `business_events`, `guards`, `lifecycle`, and `final_output`.

## Frontend

The frontend fixture `dinamoShadowUniversalTrace.ts` renders through `UniversalTracePanel`. The test validates `requirements_complete`, `human_handoff_requested`, `dry-run`, and visible final output.

## Commands and Results

```bash
uv run pytest tests/agent_runtime/test_dinamo_shadow_e2e.py -q
```

Result: `4 passed, 1 warning`

```bash
uv run ruff check atendia/agent_runtime tests/agent_runtime/test_dinamo_shadow_e2e.py
```

Result: failed because broad `atendia/agent_runtime` includes pre-existing unrelated lint in `canonical.py`, `model_provider.py`, `operational_state_reconciler.py`, `provider_reliability.py`, and `runtime.py`.

Adjusted focused command:

```bash
uv run ruff check tests/agent_runtime/test_dinamo_shadow_e2e.py atendia/agent_runtime/business_events.py atendia/agent_runtime/universal_turn_trace.py atendia/agent_runtime/workflow_events.py atendia/agent_runtime/advisor_pipeline.py
```

Result: `All checks passed!`

```bash
uv run pytest tests/agent_runtime/test_dinamo_shadow_e2e.py tests/agent_runtime/test_business_events.py tests/agent_runtime/test_universal_turn_trace.py tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_mandatory_tool_contract.py tests/agent_runtime/test_tenant_domain_contract.py -q
```

Result: `54 passed, 1 warning`

```bash
uv run pytest tests/agent_runtime -m "not integration_db" -q
```

Result: `196 passed, 27 deselected, 2 warnings`

```bash
npm exec -- vitest run UniversalTracePanel
```

Result: `1 passed, 8 tests passed`

```bash
npm run typecheck
```

Result: passed

```bash
npm exec -- biome check src/features/turn-traces/__fixtures__/dinamoShadowUniversalTrace.ts tests/features/turn-traces/UniversalTracePanel.test.tsx
```

Result: `Checked 2 files in 29ms. No fixes applied.`

## Hardcode Scan

No Dinamo tenant ID, Dinamo name, or Dinamo agent ID was added to core runtime. The broad scan still finds pre-existing generic domain terms in core runtime (`vehicle_credit_sales`, `moto`, `credito`) in existing files such as `quote_safety.py` and `tenant_domain_contract.py`; this task did not add new core runtime hardcodes.

## Risks Remaining

- Config is fixture/report only; no DB persistence was applied.
- Legacy runner remains required for production fallback.
- Real workflow/action side effects are still disabled and untested by design.
- Durable cross-turn idempotency/persistence should be added before any live execution.
- Existing core runtime still contains pre-existing generic vehicle-credit terms outside this task.

## Decision Final

`DINAMO_SHADOW_READY`

## Recommended Next Step

Run a human-reviewed real replay dataset against this shadow config, still with `live_send_enabled=false`, `actions_enabled=false`, and `workflow_side_effects_enabled=false`, before considering a single-contact smoke approval.

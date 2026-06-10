# Real Agent Test Lab Evidence Review

Date: 2026-06-08

Current decision: `REAL_AGENT_TEST_LAB_EVIDENCE_REVIEW_READY`

Next decision target: `READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL`

No smoke, WhatsApp send, outbox live dispatch, workflow side effects, action side
effects, canary, open production, staging, git stage, commit, cleanup, or
destructive command was executed during this review.

## Evidence Reviewed

Primary evidence file:

- `reports/real_agent_test_lab_no_send_2026_06_07.md`

The primary report contains historical failed sections below the latest result.
For this gate, the authoritative result is the latest passed section at the top:

- `run_status=passed`
- Internal Test Lab decision: `TEST_LAB_PASSED`
- Final gate decision recorded there: `REAL_AGENT_TEST_LAB_NO_SEND_READY`
- `execution_mode=runtime_v2_agent_service`
- OpenAI API real: `true`
- Model: `gpt-4o-mini`
- `suite_id=a9059d97-7732-46d2-9d0b-c95bf2d73a28`
- `test_run_id=c9c9baa0-308d-4b6b-b9fb-44b39b4c2901`
- Test Lab tenant: `5528e854-f446-46e8-bac0-bac28a8492fe`
- Test Lab agent version: `6d4e3937-3621-4951-b9ab-bdcd05dd1577`
- `send_decision=no_send` on every turn
- `universal_turn_trace` present on every turn
- policy passed on every turn
- required tools succeeded on turns that required hard data
- no required tool skipped or failed in the passed run
- API key value was not printed or written

## Scenario Evidence

Scenario A, negocio ambiguo:

- `Tengo negocio` did not write a hard plan.
- The agent asked SAT/RIF vs sin comprobantes instead of assuming a plan.
- `No tengo SAT` resolved through `credit_plan.resolve`.
- State writes after evidence:
  - `plan_selection=20%`
  - `down_payment_percent=20`
  - evidence `requirements:sin_comprobantes_20`
- `La Adventure` executed `catalog.search` and wrote:
  - `product_selection=Adventure Elite 150 CC`
  - `product_catalog_id=adventure_elite_150_cc`

Scenario B, Skeleton / buro / tarjeta:

- `catalog.search:succeeded` for Skeleton.
- `faq.lookup:succeeded` for buro.
- `credit_plan.resolve:succeeded` for `me pagan por tarjeta`.
- State writes:
  - `product_selection=Skeleton 400 CC`
  - `product_catalog_id=skeleton_400_cc`
  - `plan_selection=10%`
  - `down_payment_percent=10`
  - `employment_seniority=24`
  - `quote_snapshot_id=quote-skeleton_400_cc-plan-10`
  - `requirements_checklist`
- `quote.resolve:succeeded` before quoting.
- `requirements.lookup:succeeded` before listing requirements.

## Verification Results Reviewed

Commands recorded in the primary evidence report:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:UV_CACHE_DIR='..\.uv-cache'
uv run ruff check atendia\agent_runtime\advisor_brain_contract.py atendia\agent_runtime\knowledge_tool_layer.py atendia\agent_runtime\advisor_pipeline.py atendia\agent_runtime\semantic_interpreter.py atendia\agent_runtime\mandatory_tools.py tests\agent_runtime\test_dinamo_income_resolution_policy.py tests\agent_runtime\test_semantic_interpreter_runtime_v2.py ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
uv run pytest tests\agent_runtime\test_dinamo_income_resolution_policy.py tests\agent_runtime\test_semantic_interpreter_runtime_v2.py tests\agent_runtime\test_product_agent_runtime_context_overlay.py -q
uv run pytest tests\product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Recorded results:

- ruff: passed
- runtime focused tests: `30 passed`
- product agent tests: `153 passed`
- product agent coverage: `100%`

## Fresh DB Audit

Fresh read-only DB audit was executed against the real Dinamo tenant:

- tenant: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- tenant name: `Dinamo Motos NL`
- approved customer/contact: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- approved phone: `+5218128889241`

Results:

- `outbound_outbox pending/retry = 0`
- `business_event_ledger side_effects_allowed = 0`

The approved contact exists in DB:

- latest conversation: `cac707aa-2963-427d-a873-c8eba6f2be8b`
- channel: `whatsapp_meta`
- status: `active`

There are no `agent_deployments` rows for the real Dinamo tenant, so no Product
Agent deployment was accidentally activated through Publish Control.

## Current Real Tenant Safety State

Read-only tenant config check for `config.agent_runtime_v2`:

- `runtime_v2_enabled=true`
- `send_enabled=false`
- `outbox_enabled=false`
- `live_send_enabled=false`
- `single_contact_smoke_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`
- `live_reactivation_allowed=false`
- `send_scope=approved_contact_only`
- `allowed_contact_ids=["05da6577-2647-4b79-ae24-2d233a22bbd3"]`
- `allowed_test_phones=["+5218128889241"]`

## Known Non-Blocking Gap

The passed Runtime V2 AgentService trace did not emit token usage per turn.
The primary report records this as `estimated_cost.status=token_usage_missing`.

This is an observability/cost-accounting gap. It does not change the send safety
result because all turns stayed in `no_send`, DB audit is zero, required tools
succeeded, policy passed, and traces were present.

## Controlled Smoke Approval Packet

This review does not activate smoke. It only prepares the approval packet.

Allowed scope:

- tenant: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- contact/customer: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- phone: `+5218128889241`
- send scope: `approved_contact_only`
- allowlist size: exactly 1 contact and exactly 1 phone

Recommended controlled text script:

1. `Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro.`
2. `me pagan por tarjeta`
3. `tengo 2 años`
4. `que papeles ocupo`
5. `te mando INE al rato`
6. `?`

Success criteria:

- Only the approved contact receives a response.
- No contact outside the allowlist is eligible.
- No generic visible copy such as `reviso el contexto`, `te doy continuidad`,
  `Dime qué dato quieres revisar`, or repeated hardcoded income questions.
- `catalog.search` validates model before model write.
- `faq.lookup` handles buro.
- `credit_plan.resolve` handles income plan.
- `quote.resolve` handles quote before any price/payment.
- `requirements.lookup` handles requirements.
- no document field is marked complete from `te mando INE al rato`.
- `universal_turn_trace` is present.
- `TurnOutput.final_message` is the only visible response authority.
- policy passes before send.
- DB post-smoke audit remains clean except expected approved-contact send
  evidence.

## Activation Plan Requiring Explicit Human Approval

The only allowed activation after explicit approval is:

- `send_enabled=true`
- `outbox_enabled=true`
- `live_send_enabled=true`
- `single_contact_smoke_enabled=true`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_active`
- `send_scope=approved_contact_only`
- `allowed_contact_ids=["05da6577-2647-4b79-ae24-2d233a22bbd3"]`
- `allowed_test_phones=["+5218128889241"]`

Must remain disabled:

- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`

Human approval text required before activation:

```text
Apruebo activar controlled single-contact smoke Dinamo Runtime V2 únicamente para el contacto 05da6577-2647-4b79-ae24-2d233a22bbd3 / +5218128889241, con send_enabled=true, outbox_enabled=true, live_send_enabled=true, single_contact_smoke_enabled=true, runtime_mode=runtime_v2_controlled_single_contact_smoke_active, send_scope=approved_contact_only, sin actions, sin workflow events, sin workflow side effects, sin canary, sin producción abierta, sin legacy fallback visible, sin provider visible fallback y con rollback inmediato ante cualquier respuesta incorrecta.
```

## Rollback Packet

If any response is wrong, robotic, generic, duplicated, tool-skipped, policy
failed, or sent outside scope, rollback immediately:

- `send_enabled=false`
- `outbox_enabled=false`
- `live_send_enabled=false`
- `single_contact_smoke_enabled=false`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- `live_reactivation_allowed=false`

Post-rollback checks:

```sql
select count(*)
from outbound_outbox
where tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5'
  and status in ('pending', 'retry');
```

```sql
select count(*)
from business_event_ledger
where tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5'
  and side_effects_allowed = true;
```

Also review:

- latest `universal_turn_trace`
- latest `TurnOutput.final_message`
- tool execution list
- StateWriter decisions
- policy result
- SendAdapter decision
- outbox recipient
- legacy fallback visible blockers

## Final Decisions

`REAL_AGENT_TEST_LAB_EVIDENCE_REVIEW_READY`

`READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL`


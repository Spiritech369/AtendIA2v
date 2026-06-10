# Controlled Single-Contact Smoke V3 Approval Packet - 2026-06-08

## Decision

`SMOKE_V3_FLOW_ORDER_READY_FOR_APPROVAL`

No smoke was activated in this task. This packet only prepares approval.

The no-send runner decision was:

`READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V3`

## Previous State

Previous blocker:

`SMOKE_V3_APPROVAL_BLOCKED_BY_FLOW_ORDER`

Real blocker:

- Tenant/product-agent route asked income before persisting seniority in the real route.
- Canonical product-agent fields were blocked by legacy visible field configuration.
- `cumple_antiguedad` was not derived from `employment_seniority`.
- After plan resolution, the runtime could lose the real next pending slot and repeat income.
- A `?` turn could trigger non-actionable `catalog.search` or free-form slot `model`.

## Fixes Applied

- Product-agent runtime now overlays canonical visible field permissions into `ContextBuilder`.
- `StateWriter` derives seniority eligibility generically from field metadata:
  - `employment_seniority=24`
  - `cumple_antiguedad=true`
- `ValidatedResponsePlan` keeps the next pending slot after `credit_plan.resolve`; if no product/model exists, pending becomes `product_selection`.
- `ValidatedResponsePlan` always emits `next_best_question` for a pending slot that is not consumed.
- `HumanResponseComposer` blocks wrong-slot questions and repairs only to the validated `next_best_question`.
- `SemanticInterpreter` normalizes free slots such as `model/modelo/product/producto` to `product_selection`.
- `catalog.search` rejects non-actionable inputs like punctuation-only continuation turns.
- Dinamo tenant runtime contract was aligned to tenant `6ad78236-1fc9-467a-858d-90d248d57ee5` and includes seniority-before-income flow policy.

No shared runtime code hardcodes a Dinamo plan, price, phone, catalog item, or credit rule.

## Tenant And Contact Scope

- Tenant: `6ad78236-1fc9-467a-858d-90d248d57ee5` / `Dinamo Motos NL`
- Agent: `c169deec-226d-55b7-bd07-270f339e75a6`
- Approved contact: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- Approved phone: `+5218128889241`
- `send_scope=approved_contact_only`
- `allowed_contact_ids=["05da6577-2647-4b79-ae24-2d233a22bbd3"]`
- `allowed_test_phones=["+5218128889241"]`
- No other contact is approved.

## Flags Confirmed Off

Backend env:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

Worker env:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

Tenant flags:

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
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`

## DB Audit

Before and after the no-send run:

- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`

Direct post-run DB audit:

- `outbox_pending_retry=0`
- `side_effects_allowed=0`

## Container Source Audit

Confirmed readable from backend and worker:

- `/app/docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json` (`324797` bytes)
- `/app/docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json` (`51395` bytes)
- `/app/docs/tenant_sources/dinamo/FAQ_DINAMO.json` (`6021` bytes)
- `/app/docs/tenant_sources/dinamo/dinamo_runtime_contract.json` (`10089` bytes)
- `/app/docs/tenant_sources/dinamo/dinamo_knowledge_sources_manifest.json` (`2179` bytes)
- `/app/docs/tenant_sources/dinamo/dinamo_test_lab_scenarios.json` (`3048` bytes)

## Tests And Verification

Ruff:

```powershell
uv run ruff check atendia/agent_runtime/context_builder.py atendia/agent_runtime/state_writer.py atendia/agent_runtime/validated_response_plan.py atendia/agent_runtime/human_response_composer.py atendia/agent_runtime/semantic_interpreter.py tests/agent_runtime/test_human_response_composer.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py ..\tools\run_controlled_smoke_readiness_no_send_v3_2026_06_08.py
```

Result:

- `All checks passed!`

Focused tests:

```powershell
uv run pytest tests/agent_runtime/test_human_response_composer.py tests/agent_runtime/test_product_agent_runtime_context_overlay.py tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_validated_response_plan_builder.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py tests/agent_runtime/test_runtime_v2_container_sources.py -q
```

Result:

- `72 passed in 1.36s`

Preflight no-send:

```powershell
uv run python ..\tools\run_controlled_smoke_readiness_no_send_v3_2026_06_08.py
```

Result:

- `decision=READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V3`
- `run_status=passed`
- `run_decision=TEST_LAB_PASSED`
- `readiness_audit.status=passed`
- `readiness_audit.failures=[]`
- `test_run_id=7ee04e69-c54a-4038-af7b-7df2ba64d3c8`
- `suite_id=3474c1dc-5b8e-4085-8620-76b0015c3337`
- tokens: `4210` total

## Preflight Turn Evidence

| Turn | Inbound | Final Message | Tools | Writes | Result |
| --- | --- | --- | --- | --- | --- |
| 1 | `hola` | `¡Hola! Para continuar, ¿cuánto tiempo llevas trabajando?` | none | none | OK, asks seniority first |
| 2 | `info porfavor` | `¿Cuánto tiempo llevas trabajando en tu empleo actual?` | none | none | OK, still seniority first |
| 3 | `tengo 2 años` | `¿Cómo recibes tus ingresos?` | none | `cumple_antiguedad`, `employment_seniority` | OK, seniority persisted and eligibility derived |
| 4 | `me pagan por transferencia` | `¿Qué modelo de moto quieres revisar?` | `credit_plan.resolve:succeeded` | `down_payment_percent`, `plan_selection` | OK, income resolved then asks model |
| 5 | `?` | `Claro, ¿qué modelo de moto quieres revisar?` | none | none | OK, resumes real pending `product_selection` |

All turns used `send_decision=no_send`.

## Recommended Smoke Script

Use only approved contact `05da6577-2647-4b79-ae24-2d233a22bbd3 / +5218128889241`.

1. `hola`
2. `info porfavor`
3. `tengo 2 años`
4. `me pagan por transferencia`
5. `vi una Skeleton`
6. `?`

Success criteria:

- seniority is requested before income,
- `employment_seniority` and `cumple_antiguedad` are written after the seniority answer,
- `credit_plan.resolve` succeeds for income,
- `plan_selection` and `down_payment_percent` are written,
- if model is missing, the bot asks for model and does not repeat income,
- `?` resumes the real pending slot,
- `catalog.search` only runs after an actionable model/category signal,
- no generic copy appears,
- no actions/workflows/canary/open production,
- no contact outside allowlist.

Rollback criteria:

- any response asks the wrong slot,
- any generic copy appears,
- any required tool is skipped/failed when hard data is needed,
- any outbox/live send appears outside the approved contact,
- any action/workflow side effect appears,
- any legacy/provider/manual visible fallback appears.

## Rollback Packet

If future live/smoke activation fails:

1. Set tenant flags:
   - `send_enabled=false`
   - `outbox_enabled=false`
   - `live_send_enabled=false`
   - `single_contact_smoke_enabled=false`
   - `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
2. Keep disabled:
   - `actions_enabled=false`
   - `workflow_events_enabled=false`
   - `workflow_side_effects_enabled=false`
   - `canary_enabled=false`
   - `open_production_enabled=false`
   - visible legacy/provider/manual fallback
3. Confirm:
   - `outbound_outbox` pending/retry = `0`
   - `business_event_ledger.side_effects_allowed=true` = `0`
   - last universal turn traces
   - last `TurnOutput.final_message`
   - no visible fallback copy

## Human Approval Text

Required exact approval text for the next step:

> Apruebo activar controlled single-contact smoke V3 para Dinamo Runtime V2 únicamente con el contacto `05da6577-2647-4b79-ae24-2d233a22bbd3 / +5218128889241`, con `send_enabled=true`, `outbox_enabled=true`, `live_send_enabled=true`, `single_contact_smoke_enabled=true`, `send_scope=approved_contact_only`, sin actions reales, sin workflow events, sin workflow side effects, sin canary, sin producción abierta, sin legacy fallback visible, sin provider visible fallback, sin manual recovery visible, y con rollback inmediato ante cualquier respuesta incorrecta.

## Final

No WhatsApp was sent. No smoke was activated. No outbox live was written. No real workflow/action side effects were enabled.

Final decision:

`SMOKE_V3_FLOW_ORDER_READY_FOR_APPROVAL`

# Controlled Single-Contact Smoke V2 Incident - 2026-06-08

## Decision

`CONTROLLED_SINGLE_CONTACT_SMOKE_V2_ROLLED_BACK`

## Scope

- Tenant ID: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- Contact ID: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- Phone: `+5218128889241`
- Conversation ID observed: `cac707aa-2963-427d-a873-c8eba6f2be8b`

## User-Visible Symptom

The smoke improved versus earlier robotic copy, but still failed:

1. It asked for income before applying the commercial seniority filter.
2. After the customer answered `Me pagan por transferencia`, it did not send a visible response.
3. After the customer sent `?`, it still did not send a visible response.

## Rollback Applied

Rollback was applied immediately after the failed smoke observation.

Effective flags after rollback:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- tenant `send_enabled=false`
- tenant `outbox_enabled=false`
- tenant `live_send_enabled=false`
- tenant `single_contact_smoke_enabled=false`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- `smoke_phase=CONTROLLED_SINGLE_CONTACT_SMOKE_V2_ROLLED_BACK`

Backend and worker were recreated after changing the environment flag.

## DB Audit After Rollback

- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`

## Observed Live Messages

Recent message sequence:

- inbound: `Hola`
- outbound: `¡Hola! Espero que estés bien. Para continuar, ¿podrías decirme cómo recibes tus ingresos?`
- inbound: `Info porfavor`
- outbound: `Para continuar, ¿podrías decirme cómo recibes tus ingresos?`
- inbound: `Me pagan por transferencia`
- inbound: `?`

The last two inbound turns produced no visible outbound message.

## Trace Finding

For `Me pagan por transferencia` and the following `?`, the runtime did receive and process the turns, but failed closed:

- router: `agent_runtime_v2_prepared_send_path`
- required tool: `credit_plan.resolve`
- tool status: `skipped`
- guard failure: `required_tool_not_succeeded_blocks_send`
- skip reason: `requirements source and explicit income signal required`

The semantic interpreter did understand the income answer:

- `user_act=answer_to_pending_slot`
- `pending_slot_answered=income_type`
- `income.present=true`
- `income.candidate=nomina_tarjeta`
- `income.evidence=Me pagan por transferencia`
- `income.confidence=0.9`

The tool call was required, but the tool could not resolve because the requirements source was unavailable inside the running backend container.

## Root Cause

The tenant config points to knowledge sources under repo-root paths:

- `docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json`
- `docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json`
- `docs/tenant_sources/dinamo/FAQ_DINAMO.json`

Those files exist on the host workspace.

However, Docker mounts only `./core` into backend/worker as `/app`.

Therefore, inside the live backend container:

- `/app/docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json` is not present.

That makes `_sources(context)` return no `requirements` source, and `credit_plan.resolve` skips. Since the tool is mandatory, the send path correctly fails closed.

This is not a Baileys problem.
This is not an outbox dispatcher problem.
This is not an OpenAI interpretation problem.
It is a live container knowledge-source mounting/path problem.

## Secondary Design Issue

The flow still starts with `pending_slot=income_type`.

The user correctly noted that Dinamo should filter by employment seniority first. The repo already contains rules/tests that describe the commercial order:

`antiguedad -> plan/opciones -> modelo/catalogo -> cotizacion -> documentos`

But the live conversation state/pending slot was still `income_type`, so the runtime asked for income first.

This means the next fix needs two parts:

1. Make tenant knowledge sources available to backend/worker in live.
2. Align Runtime V2 pending-slot derivation with the tenant flow policy so seniority is requested before income when the flow requires it.

## Correct Fix Direction

Do not patch with keyword rules.

Required fix:

- Mount or package tenant knowledge sources so backend/worker can read them in Docker.
- Add a startup/readiness check that fails smoke activation if any configured knowledge source path is missing inside the running container.
- Add a no-send/live-candidate parity test that verifies `catalog.search`, `credit_plan.resolve`, `requirements.lookup`, and `faq.lookup` all see the same source paths.
- Add a flow-policy test proving Dinamo asks employment seniority before income/plan when the tenant policy requires seniority gating.
- Keep `credit_plan.resolve` tenant-aware and requirements-driven.

## Current State

Live smoke is off.

Do not reactivate until:

- backend/worker can read all tenant knowledge sources,
- `credit_plan.resolve` succeeds for `Me pagan por transferencia`,
- first-turn flow asks seniority before income when no seniority is known,
- mini suite no-send passes,
- DB audit stays clean,
- approval packet is regenerated.

## Fix Applied After Rollback

Implementation completed in no-send only.

Changes applied:

- Mounted tenant source files into runtime containers:
  - `backend`: `./docs/tenant_sources:/app/docs/tenant_sources:ro`
  - `worker`: `./docs/tenant_sources:/app/docs/tenant_sources:ro`
  - `workflow-worker`: `./docs/tenant_sources:/app/docs/tenant_sources:ro`
- Hardened runtime source root detection so host tests and containers resolve the same tenant source tree instead of the empty `core/docs/tenant_sources` directory.
- Added container-aware source parity tests for no-send/live-candidate source loading.
- Added flow-policy coverage for Dinamo seniority-before-income:
  - first generic credit/info turn asks employment seniority before income,
  - greeting/info does not jump to income as the first business slot,
  - seniority answer is consumed before income,
  - income answer after seniority runs `credit_plan.resolve`.
- Updated Dinamo tenant runtime contract and test fixture flow policy:
  - `seniority_before_income=true`
  - `seniority_slot=employment_seniority`
  - `income_slot=income_type`
  - `seniority_minimum_months=6`
- Updated tenant DB config with the same flow policy while keeping all live/send flags false.
- Recreated backend and worker after mount/config changes.

## Verification After Fix

Commands run:

- Host tests: `uv run pytest tests/agent_runtime/test_runtime_v2_container_sources.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py -q`
  - Result: `36 passed`
- Host lint: `uv run ruff check atendia/agent_runtime/semantic_interpreter.py atendia/agent_runtime/validated_response_plan.py atendia/agent_runtime/knowledge_tool_layer.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py tests/agent_runtime/test_runtime_v2_container_sources.py`
  - Result: `All checks passed!`
- Backend container tests: `docker compose exec -T backend uv run pytest tests/agent_runtime/test_runtime_v2_container_sources.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py -q`
  - Result: `36 passed`

Container source audit:

- backend can read `/app/docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json` (`324797` bytes)
- backend can read `/app/docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json` (`51395` bytes)
- backend can read `/app/docs/tenant_sources/dinamo/FAQ_DINAMO.json` (`6021` bytes)
- worker can read the same three source files with the same sizes.

Runtime env audit:

- backend `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- backend `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- backend `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- worker `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- worker `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- worker `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

Tenant DB flag audit:

- `send_enabled=false`
- `outbox_enabled=false`
- `live_send_enabled=false`
- `single_contact_smoke_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- `smoke_phase=CONTROLLED_SINGLE_CONTACT_SMOKE_V2_ROLLED_BACK`

DB side-effect audit:

- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`

## Post-Fix Decision

`CONTROLLED_SMOKE_V2_BLOCKERS_FIXED_NO_SEND_READY`

The two observed blockers are fixed and covered by tests:

1. Container runtime can read tenant source files, so required tools no longer fail solely because `docs/tenant_sources` is missing in `/app`.
2. Dinamo flow policy now requests employment seniority before income when no seniority is known.

Live remains off. No WhatsApp, smoke, outbox live, actions, workflow events, canary, or open production were activated during this fix.

Next step before any reactivation: regenerate a controlled single-contact smoke approval packet from this no-send baseline.

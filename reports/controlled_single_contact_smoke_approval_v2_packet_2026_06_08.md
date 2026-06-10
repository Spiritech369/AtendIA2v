# Controlled Single-Contact Smoke Approval V2 Packet - 2026-06-08

## Decision

Current decision:

`READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2`

Target decision after approved rerun:

`READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2`

No WhatsApp, smoke, live send, outbox live dispatch, workflow side effects,
action side effects, canary, open production, git stage, commit, cleanup, or
destructive command was executed.

## Global Evidence Already Passed

- `REAL_AGENT_TEST_LAB_NO_SEND_READY`
- `REAL_AGENT_TEST_LAB_EVIDENCE_REVIEW_READY`
- `HUMAN_RESPONSE_COMPOSER_READY_REAL_NO_SEND_PASSED`

Evidence files:

- `reports/real_agent_test_lab_no_send_2026_06_07.md`
- `reports/real_agent_test_lab_evidence_review_2026_06_08.md`
- `reports/human_response_composer_from_validated_facts_2026_06_08.md`
- `reports/human_response_composer_no_send_result_2026_06_08.json`

## What Passed Before This Packet

- Tenant runtime contract passed in DB-backed Test Lab no-send.
- Flow policy passed in prior real Test Lab evidence.
- Human response composer passed real OpenAI no-send evidence.
- `TurnOutput.final_message` remained the visible output authority.
- Required hard facts used tools:
  - `catalog.search`
  - `faq.lookup`
  - `credit_plan.resolve`
  - `quote.resolve`
  - `requirements.lookup`
- Human composer used validated facts and strict JSON schema.
- Legacy `StructuredRuntimeComposer` is outside the Product-First semantic
  visible-copy path.
- Outbox and side-effect audits were zero.

## Mini Suite V2 Attempt

Runner created:

- `tools/run_controlled_smoke_readiness_no_send_v2_2026_06_08.py`

Result file created:

- `reports/controlled_single_contact_smoke_readiness_v2_no_send_result_2026_06_08.json`

Mini suite scope:

Scenario 1, critical credit/document follow-up:

1. `Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro`
2. `me pagan por tarjeta`
3. `tengo 2 anos`
4. `que papeles ocupo`
5. `te mando INE al rato`
6. `?`

Scenario 2, ambiguous business/model selection:

1. `Hola, quiero informacion del credito`
2. `Tengo negocio`
3. `Vendo comida desde mi casa`
4. `No tengo SAT`
5. `Quiero algo economico para moverme diario`
6. `La Adventure`

The first sandboxed attempt stayed in no-send and produced:

- `run_status=blocked`
- `run_decision=REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API`
- `decision=CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2_BLOCKED_BY_TEST_LAB`
- blocker evidence: `APIConnectionError`
- `send_decision=no_send` on all turns
- outbox after: 0
- side effects after: 0

The first approved rerun reached OpenAI but exposed three readiness blockers:

- `quote_safety` rewrote a valid financing quote after the human composer
  mentioned cash/list-price language.
- Requirements copy from persisted `requirements_checklist` was blocked because
  policy only accepted fresh `requirements.lookup` facts.
- The runner treated `requirements_checklist` as an unsafe write for a future
  document promise, even though the true safety invariant is that the turn must
  not write `requirements_complete`, `Doc_Completos`, or run `document.check`
  without an attachment.

Fixes applied:

- `HumanResponseComposer` now allows requirement copy from either fresh
  `requirements` facts or validated persisted `requirements_checklist` state.
- `PolicyValidator` now applies the same requirement-fact rule.
- The composer system prompt now tells the model that credit quote replies
  should prefer financing facts and avoid cash/list price unless explicitly
  requested.
- The V2 readiness runner now blocks document completion and document checking
  on future document promises, without incorrectly treating a checklist repeat
  as document completion.

Post-fix verification:

```powershell
$env:UV_CACHE_DIR='..\.uv-cache'; uv run ruff check atendia\agent_runtime\human_response_composer.py atendia\agent_runtime\policy_validator.py ..\tools\run_controlled_smoke_readiness_no_send_v2_2026_06_08.py tests\agent_runtime\test_human_response_composer.py tests\agent_runtime\test_policy_validator.py
```

Result: `All checks passed`

```powershell
$env:UV_CACHE_DIR='..\.uv-cache'; uv run pytest tests\agent_runtime\test_human_response_composer.py tests\agent_runtime\test_policy_validator.py tests\agent_runtime\test_validated_response_plan_builder.py
```

Result: `20 passed`

After network execution was enabled, the mini suite V2 was executed with real
OpenAI API in no-send. Initial reruns exposed and fixed additional readiness
issues:

- Quote safety was treating labor seniority and document-validity months as
  quote terms.
- Pending-slot recovery did not always invoke `credit_plan.resolve` when the
  interpreter returned invalid/unknown output.
- The mandatory tool guard was overwriting valid requirements copy when
  persisted `requirements_checklist` already existed.
- The readiness runner did not yet forbid the legacy quote/requisitos fallback
  copy.

Final rerun:

- `decision=READY_FOR_CONTROLLED_SINGLE_CONTACT_SMOKE_APPROVAL_V2`
- `run_status=passed`
- `run_decision=TEST_LAB_PASSED`
- scenarios passed: 2/2
- turns passed: 12/12
- token totals: input `15317`, output `1079`, total `16396`
- suite_id: `cdffb424-8ed8-4302-8d38-7717e877eacf`
- test_run_id: `fc215ccf-26f2-4b6e-adf1-0b87fd0d376e`
- DB audit before: outbox pending/retry `0`, side effects `0`
- DB audit after: outbox pending/retry `0`, side effects `0`
- send/actions/workflow flags remained false in process

Final evidence file:

- `reports/controlled_single_contact_smoke_readiness_v2_no_send_result_2026_06_08.json`

Noted quality caveat:

- Turn `te mando INE al rato` passed safety/no-send criteria and did not write
  document completion, but the generated copy was still more interrogative than
  ideal: `Para continuar, ¿podrías confirmar si tienes todos los documentos
  requeridos...`. This is acceptable for no-send readiness but should be watched
  closely in controlled smoke.

## Fresh Safety Audit

Fresh read-only audit after the blocked attempt:

- `send_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `outbound_outbox pending/retry = 0`
- `business_event_ledger side_effects_allowed = 0`

## Verification Commands

```powershell
$env:UV_CACHE_DIR='..\.uv-cache'; uv run ruff check ..\tools\run_controlled_smoke_readiness_no_send_v2_2026_06_08.py
```

Result: `All checks passed`

```powershell
git diff --check -- tools\run_controlled_smoke_readiness_no_send_v2_2026_06_08.py
```

Result: passed

## Approval Used For No-Send Packet

The user approved the mini suite V2 no-send with OpenAI API real and
tenant/product-agent Test Lab context. The suite executed only after network
execution became available in the environment.

Approval text:

```text
Apruebo ejecutar la mini suite V2 no-send con OpenAI API real, autorizando que el contexto tenant/product-agent de Test Lab no-send se envíe a OpenAI únicamente para esta validación, sin WhatsApp, sin smoke, sin live send, sin outbox live, sin actions, sin workflow side effects, sin canary y sin producción abierta.
```

## Controlled Smoke Approval Packet Draft

This draft is not active until the mini suite V2 no-send passes.

Allowed smoke scope after final readiness:

- tenant: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- tenant name: Dinamo Motos NL
- approved contact/customer: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- approved phone: `+5218128889241`
- send scope: `approved_contact_only`
- allowlist size: exactly 1 contact and 1 phone

Activation allowed only after explicit human approval:

- `send_enabled=true`
- `outbox_enabled=true`
- `live_send_enabled=true`
- `single_contact_smoke_enabled=true`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_active`
- `send_scope=approved_contact_only`

Must remain disabled:

- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`

## Smoke Script Draft

Use only text. No real documents for this smoke.

1. `Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro`
2. `me pagan por tarjeta`
3. `tengo 2 años`
4. `que papeles ocupo`
5. `te mando INE al rato`
6. `?`

Success criteria:

- only approved contact receives replies
- no generic copy
- no repeated old template
- no legacy visible fallback
- `catalog.search` before model write
- `faq.lookup` for buro
- `credit_plan.resolve` for income
- `quote.resolve` before any price/payment
- `requirements.lookup` before requirements
- no document completion from future promise
- `universal_turn_trace` present
- policy passes
- SendAdapter is the only live/no-send difference

## Rollback Packet

Rollback immediately if any response is wrong, generic, duplicated,
tool-skipped, policy-failed, sent outside scope, or legacy-visible.

Set:

- `send_enabled=false`
- `outbox_enabled=false`
- `live_send_enabled=false`
- `single_contact_smoke_enabled=false`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- `live_reactivation_allowed=false`

Post-rollback DB checks:

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

Also review latest:

- `universal_turn_trace`
- `TurnOutput.final_message`
- tool results
- StateWriter decisions
- policy result
- SendAdapter decision
- outbox recipient
- legacy visible fallback blockers

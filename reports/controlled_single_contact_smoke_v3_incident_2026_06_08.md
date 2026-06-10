# Controlled Single-Contact Smoke V3 Incident - 2026-06-08

## Incident

During controlled single-contact smoke V3 for approved contact
`05da6577-2647-4b79-ae24-2d233a22bbd3 / +5218128889241`, the customer sent:

1. `Hola`
2. `Busco info`
3. `15 meses`

The runtime responded visibly:

> Parece que no puedo registrar tu antigüedad laboral de 15 meses en este momento, ya que el campo no está visible. Si tienes más información o preguntas, ¡estaré aquí para ayudarte!

This response is invalid because it exposes internal StateWriter/field visibility
reasoning to the customer.

## Immediate Rollback

Rollback was executed immediately.

Global `.env`:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

Tenant `6ad78236-1fc9-467a-858d-90d248d57ee5`:

- `send_enabled=false`
- `outbox_enabled=false`
- `live_send_enabled=false`
- `single_contact_smoke_enabled=false`
- `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `workflow_side_effects_enabled=false`
- `canary_enabled=false`
- `open_production_enabled=false`
- `legacy_fallback_enabled=false`
- `provider_visible_fallback_enabled=false`
- `manual_recovery_visible_enabled=false`

Post-rollback audit:

- backend env: `false / false / false`
- worker env: `false / false / false`
- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`

## Root Cause

The live trace for conversation `cac707aa-2963-427d-a873-c8eba6f2be8b`,
turn `12`, showed:

- ChatGPT correctly interpreted `15 meses` as `employment_seniority=15`.
- StateWriter blocked the write:
  - field: `employment_seniority`
  - reason: `field_not_visible`
- The tenant domain contract had `employment_seniority`, but the active agent
  still carried legacy visible field keys.
- HumanResponseComposer allowed the provider to expose the blocked
  StateWriter reason in the final message.

The failure was not a business ambiguity issue. It was:

1. field visibility authority mismatch between legacy active agent fields and
   tenant/product-agent contract fields,
2. missing visible-copy policy for StateWriter internal reasons.

## Fix Applied

Code:

- `core/atendia/agent_runtime/state_writer.py`
  - `_visible_fields()` now includes tenant contract field metadata keys in
    addition to active-agent visible fields.
  - This prevents canonical contract fields from being blocked by legacy
    visible field lists.

- `core/atendia/agent_runtime/human_response_composer.py`
  - Added policy blocking for internal StateWriter visibility text:
    - `field_not_visible`
    - `campo no está visible`
    - `StateWriter`

Tests:

- `core/tests/agent_runtime/test_declarative_state_writer.py`
  - Added regression for contract-declared `employment_seniority` with legacy
    active-agent visible fields.
  - Confirms seniority write is accepted and eligibility is derived.

- `core/tests/agent_runtime/test_human_response_composer.py`
  - Added regression blocking `campo no está visible` from visible copy.

## Verification

Ruff:

```powershell
$env:UV_CACHE_DIR = "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core\.uv-cache"
uv run ruff check atendia/agent_runtime/state_writer.py atendia/agent_runtime/human_response_composer.py tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_human_response_composer.py
```

Result:

- `All checks passed!`

Focused tests:

```powershell
$env:UV_CACHE_DIR = "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core\.uv-cache"
uv run pytest tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_human_response_composer.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py tests/agent_runtime/test_validated_response_plan_builder.py -q
```

Result:

- `68 passed`
- One pytest cache warning due local `.pytest_cache` permission, not test failure.

No-send preflight after fix:

```powershell
$env:UV_CACHE_DIR = "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core\.uv-cache"
uv run python ..\tools\run_controlled_smoke_readiness_no_send_v3_2026_06_08.py
```

Result:

- blocked by OpenAI API/provider issue
- DB audit stayed clean
- turn 3 confirmed state writes:
  - `employment_seniority`
  - `cumple_antiguedad`

Because OpenAI failed, the system is not ready for reactivation.

## Decision

`CONTROLLED_SMOKE_V3_ROLLED_BACK_FIELD_VISIBILITY_INCIDENT_FIXED_TESTED_NO_SEND_BLOCKED_BY_OPENAI`

## Next Gate

Do not reactivate live yet.

Required before any new activation:

1. Re-run no-send preflight with OpenAI working.
2. Confirm full script passes.
3. Confirm DB audit remains zero.
4. Prepare V3 retry approval packet.
5. Request explicit human approval again.

## 2026-06-09 Gate Attempt

Gate requested:

`SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX`

Result:

`SMOKE_V3_BLOCKED_BY_OPENAI_API`

No smoke was activated. No WhatsApp was enabled. No live outbox was written.

Checks:

- `OPENAI_API_KEY` in `core/.env`: `present=false`
- `OPENAI_API_KEY` in process env: `present=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`

Docker status:

- `desktop-linux` context failed: Docker pipe not found.
- `default` context failed: Docker pipe not found.
- Runtime DB/backend/worker audit could not run because Docker daemon was not
  available.

Blocked work:

- Could not run `runtime_v2_agent_service` no-send preflight.
- Could not confirm backend/worker env from containers.
- Could not confirm DB audit from Postgres.

Safety:

- Local `.env` still has send/actions/workflow flags set to false.
- No reactivation was attempted.

Required to retry:

1. Start Docker Desktop.
2. Restore/load `OPENAI_API_KEY` locally without printing it.
3. Re-run this gate before any smoke approval.

## 2026-06-09 Continuation Attempt

Gate still requested:

`SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX`

Current result:

`SMOKE_V3_BLOCKED_BY_OPENAI_API`

Safety state:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- backend env: `false / false / false`
- worker env: `false / false / false`
- tenant `send_enabled=false`
- tenant `outbox_enabled=false`
- tenant `live_send_enabled=false`
- tenant `single_contact_smoke_enabled=false`
- tenant `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`

Docker state:

- `postgres-v2`: running healthy
- `redis-v2`: running healthy
- `backend`: running, `/health` OK
- `worker`: running
- `baileys-bridge`: stopped for this no-send gate

OpenAI key:

- `core/.env`: `OPENAI_API_KEY` not present
- current process env: `OPENAI_API_KEY` not present
- backend container env: `OPENAI_API_KEY` not present

Verification that does not require OpenAI:

```powershell
$env:UV_CACHE_DIR = "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core\.uv-cache"
uv run ruff check atendia/agent_runtime/state_writer.py atendia/agent_runtime/human_response_composer.py tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_human_response_composer.py
```

Result:

- `All checks passed!`

```powershell
$env:UV_CACHE_DIR = "C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core\.uv-cache"
uv run pytest tests/agent_runtime/test_declarative_state_writer.py tests/agent_runtime/test_human_response_composer.py tests/agent_runtime/test_semantic_interpreter_runtime_v2.py tests/agent_runtime/test_validated_response_plan_builder.py -q
```

Result:

- `68 passed`

Blocked work:

- Cannot run the real OpenAI-backed `runtime_v2_agent_service` no-send preflight.

Required to retry:

1. Add/load `OPENAI_API_KEY` locally without printing it.
2. Re-run `tools/run_controlled_smoke_readiness_no_send_v3_2026_06_08.py`.
3. Keep Baileys stopped and tenant/global send flags false during the retry.

## 2026-06-09 Second Continuation Attempt

Gate still requested:

`SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX`

Current result:

`SMOKE_V3_BLOCKED_BY_OPENAI_API`

Evidence:

- `OPENAI_API_KEY` in `core/.env`: `present=false`
- `OPENAI_API_KEY` in current process env: `present=false`
- `OPENAI_API_KEY` in backend container env: `present=false`
- `.env` runtime flags:
  - `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
  - `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
  - `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- backend env: `false / false / false`
- tenant:
  - `send_enabled=false`
  - `outbox_enabled=false`
  - `live_send_enabled=false`
  - `single_contact_smoke_enabled=false`
  - `runtime_mode=runtime_v2_controlled_single_contact_smoke_failed_no_send`
- DB audit:
  - `outbound_outbox` pending/retry: `0`
  - `business_event_ledger.side_effects_allowed=true`: `0`
- services:
  - `postgres-v2`: healthy
  - `redis-v2`: healthy
  - `backend`: running
  - `worker`: running
  - `baileys-bridge`: not running

No preflight was executed because OpenAI API is unavailable. No smoke/live was
activated.

Blocking condition has now repeated across consecutive gate attempts. The next
action requires loading `OPENAI_API_KEY` locally without printing it.

## 2026-06-09 Key Name Correction And Gate Close

Gate requested:

`SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX`

Correction:

- The real configured environment variable is `ATENDIA_V2_OPENAI_API_KEY`,
  because AtendIA settings use the `ATENDIA_V2_` prefix.
- Previous checks only looked for `OPENAI_API_KEY`; that was a false-negative
  OpenAI availability audit.
- The key was confirmed present without printing it:
  - `core/.env`: `ATENDIA_V2_OPENAI_API_KEY present=true length=164`
  - backend container: `ATENDIA_V2_OPENAI_API_KEY present=true length=164`
  - worker container: `ATENDIA_V2_OPENAI_API_KEY present=true length=164`

Safety state before execution:

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- backend env: `false / false / false`
- worker env: `false / false / false`
- `baileys-bridge`: not running
- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`
- Product Agent live deployments for tenant: `0`

No-send preflight:

- Script: `tools/run_controlled_smoke_readiness_no_send_v3_2026_06_08.py`
- Result JSON:
  `reports/controlled_single_contact_smoke_v3_preflight_after_internal_leak_fix_result_2026_06_09.json`
- Suite ID: `13a3883f-64ad-4489-aeeb-bc673188c64e`
- Test run ID: `2347e012-ffd6-4bf3-93ca-e2385c98872c`
- Run status: `passed`
- Run decision: `TEST_LAB_PASSED`
- Final gate decision:
  `SMOKE_V3_PREFLIGHT_NO_SEND_AFTER_INTERNAL_LEAK_FIX_READY`

Executed script:

1. `hola`
2. `info porfavor`
3. `15 meses`
4. `me pagan por transferencia`
5. `?`

Visible messages generated in no-send, ASCII-normalized for console display
(exact Unicode text is preserved in the result JSON):

1. `Hola. Para continuar, cuanto tiempo llevas trabajando?`
2. `Cuanto tiempo llevas trabajando en tu empleo actual?`
3. `Para continuar, podrias decirme como recibes tus ingresos?`
4. `Para continuar, que modelo de moto quieres revisar?`
5. `Hola, que modelo de moto quieres revisar?`

Validation:

- `hola` and `info porfavor` did not ask income before seniority.
- `15 meses` wrote:
  - `employment_seniority`
  - `cumple_antiguedad`
- After `15 meses`, the runtime moved to `income_type`; it did not ask
  seniority again.
- `me pagan por transferencia` executed `credit_plan.resolve` successfully and
  wrote:
  - `plan_selection`
  - `down_payment_percent`
- `?` resumed the real pending slot: `product_selection`.
- No visible message contained:
  - `field_not_visible`
  - `StateWriter`
  - internal error text
  - JSON
  - trace text
  - generic recovery copy
- Every turn had `send_decision=no_send`.

Token usage:

- Input tokens: `3927`
- Output tokens: `343`
- Total tokens: `4270`

Safety state after execution:

- backend env: `false / false / false`
- worker env: `false / false / false`
- `outbound_outbox` pending/retry: `0`
- `business_event_ledger.side_effects_allowed=true`: `0`
- Product Agent live deployments for tenant: `0`
- No WhatsApp was sent.
- No smoke was activated.
- No outbox live was written.
- No workflows/actions/canary/open production were activated.

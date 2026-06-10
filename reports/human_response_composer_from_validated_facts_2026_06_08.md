# Human Response Composer From Validated Facts - 2026-06-08

## Decision

Final decision: `HUMAN_RESPONSE_COMPOSER_READY_REAL_NO_SEND_PASSED`

Runtime path: DB-backed Test Lab `runtime_v2_agent_service`

Mode: `no_send`

OpenAI API real: yes

WhatsApp/live/smoke/outbox/workflow side effects: not activated

## What Changed

- Added `ValidatedResponsePlan` and `ValidatedResponsePlanBuilder`.
- Added `HumanResponseComposer` with a strict JSON schema contract.
- Runtime V2 semantic decisions now use `HumanResponseComposer` instead of
  `StructuredRuntimeComposer` as the primary visible-copy author.
- The composer writes from validated facts, tool summaries and allowed next
  question only.
- `StructuredRuntimeComposer` remains available only for legacy/degraded paths.
- The validated response plan now exposes `pending_slot`/`question_slot` to
  runtime state persistence, so the next DB-backed turn receives the real
  pending slot.
- `pending_confirmation` is truncated to the DB column limit while
  `_runtime_v2.last_pending_question` keeps the full message in JSONB.
- Composer OpenAI token usage is recorded in trace metadata for Test Lab
  evidence.
- Policy checks block generic progress copy, internal text, unsupported prices,
  unsupported requirements, false slot consumption and approval promises.

## Files Added

- `core/atendia/agent_runtime/validated_response_plan.py`
- `core/atendia/agent_runtime/human_response_composer.py`
- `core/tests/agent_runtime/test_validated_response_plan_builder.py`
- `core/tests/agent_runtime/test_human_response_composer.py`
- `core/tests/agent_runtime/test_runtime_state_persistence.py`
- `tools/run_human_response_composer_no_send_2026_06_08.py`
- `reports/human_response_composer_no_send_result_2026_06_08.json`

## Files Updated

- `core/atendia/agent_runtime/advisor_pipeline.py`
- `core/atendia/agent_runtime/policy_validator.py`
- `core/atendia/agent_runtime/runtime_state_persistence.py`
- `core/atendia/agent_runtime/universal_turn_trace.py`
- `core/atendia/product_agents/test_lab.py`
- `core/atendia/agent_runtime/__init__.py`
- `core/tests/agent_runtime/test_semantic_interpreter_runtime_v2.py`
- `docs/architecture/product_first_runtime_single_route.md`
- `docs/architecture/product_first_test_lab.md`
- `docs/architecture/feature_readiness_matrix.md`
- `specs/001-product-first-agent-platform/tasks.md`

## Real No-Send Evidence

Command:

```powershell
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'; uv run python ..\tools\run_human_response_composer_no_send_2026_06_08.py
```

Result:

- `run_status=passed`
- `run_decision=TEST_LAB_PASSED`
- `decision=HUMAN_RESPONSE_COMPOSER_READY_REAL_NO_SEND_PASSED`
- scenarios: 2
- turns: 7
- `send_decision=no_send` on all turns
- required tools: no skipped/failed required tools
- `composer_audit=passed`
- forbidden generic copy found: none
- trace IDs present

## Exact Messages

Scenario: `Pending income greeting guard`

1. Inbound: `Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro`
   Final: `Para continuar, ¿podrías decirme cómo recibes tus ingresos?`
   Tools: `catalog.search`, `faq.lookup`
   State writes: `product_selection`, `product_catalog_id`

2. Inbound: `hola`
   Final: `¡Hola! Espero que estés bien. Para continuar, ¿podrías decirme cómo recibes tus ingresos?`
   `user_act=greeting`, `pending_slot=income_type`, `slot_consumed=false`
   Tools: none
   State writes: none

3. Inbound: `ya te dije`
   Final: `Entiendo que esto puede ser confuso. Actualmente, necesitamos saber cómo recibes tus ingresos para continuar con el proceso. ¿Podrías compartir esa información?`
   `user_act=frustration`, `pending_slot=income_type`, `slot_consumed=false`
   Tools: none
   State writes: none

Scenario: `Skeleton buro tarjeta quote requirements`

1. Inbound: `Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro`
   Final: `Para continuar, ¿podrías decirme cómo recibes tus ingresos?`
   Tools: `catalog.search`, `faq.lookup`
   State writes: `product_selection`, `product_catalog_id`

2. Inbound: `me pagan por tarjeta`
   Final: `Para continuar, ¿podrías decirme tu nivel de antigüedad en tu empleo actual?`
   Tools: `credit_plan.resolve`
   State writes: `plan_selection`, `down_payment_percent`

3. Inbound: `tengo 2 anos`
   Final: `Tu cotización para la Skeleton 400 CC con un plan del 10% ya está lista. El pago inicial es de 8,147 MXN y las cuotas quincenales son de 3,236 MXN durante 72 quincenas. ¿Te gustaría saber más sobre el proceso?`
   Tools: `quote.resolve`
   State writes: `employment_seniority`, `quote_snapshot_id`

4. Inbound: `que papeles ocupo`
   Final: `Para el plan de Nómina Tarjeta al 10%, necesitarás enviar los siguientes documentos: INE vigente por ambos lados, un comprobante de domicilio (menos de 2 meses), dos estados de cuenta recientes y un mes de nómina dentro del estado de cuenta. ¿Te gustaría más información sobre alguno de estos requisitos?`
   Tools: `requirements.lookup`
   State writes: `plan_selection`, `down_payment_percent`, `requirements_checklist`

## Token Usage

- input tokens: 9,725
- output tokens: 626
- total tokens: 10,351
- estimated cost: `cost_rate_not_configured`

## DB Audit

Before:

- `outbound_outbox pending/retry = 0`
- `business_event_ledger side_effects_allowed = 0`

After:

- `outbound_outbox pending/retry = 0`
- `business_event_ledger side_effects_allowed = 0`

## Tests Executed

```powershell
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'; $env:ATENDIA_TEST_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test'; uv run pytest tests\agent_runtime\test_human_response_composer.py tests\agent_runtime\test_validated_response_plan_builder.py tests\agent_runtime\test_semantic_interpreter_runtime_v2.py tests\agent_runtime\test_state_writer_persists_between_turns_db_backed.py tests\agent_runtime\test_runtime_state_persistence.py tests\product_agents\test_agent_test_lab_runner.py -q
```

Result: `83 passed`

```powershell
uv run ruff check atendia\agent_runtime\human_response_composer.py atendia\agent_runtime\runtime_state_persistence.py tests\agent_runtime\test_human_response_composer.py tests\agent_runtime\test_runtime_state_persistence.py ..\tools\run_human_response_composer_no_send_2026_06_08.py
```

Result: `All checks passed`

```powershell
git diff --check -- core\atendia\agent_runtime\human_response_composer.py core\atendia\agent_runtime\runtime_state_persistence.py core\tests\agent_runtime\test_human_response_composer.py core\tests\agent_runtime\test_runtime_state_persistence.py tools\run_human_response_composer_no_send_2026_06_08.py
```

Result: passed

## Safety

- No WhatsApp activation.
- No smoke activation.
- No outbox live write.
- No workflow/action side effects.
- No SendAdapter live behavior changed.
- No tenant-specific hardcode added to generic HumanResponseComposer.

## Notes

- The local `core/.env` begins with a UTF-8 BOM, so the first env var can be
  ignored by Pydantic and the local runner can fall back to the default DB port
  `5432`. For this evidence run, `ATENDIA_V2_DATABASE_URL` was injected in the
  process environment to target `localhost:5433`.
- Composer output is now human-composed from validated facts, but the greeting
  copy can still be improved stylistically in later Test Lab iterations.

# Real AgentService Test Lab No-Send

Date: 2026-06-07

Decision: `REAL_AGENT_TEST_LAB_NO_SEND_READY`

## Scope

Implemented the next Product-First Test Lab slice for DB-backed no-send runs.
The diagnostic direct model path is now explicit as `openai_direct_provider`;
the readiness path is `runtime_v2_agent_service`, which executes Runtime V2
`AgentService` in `no_send` and requires a runtime contract before model/tool
execution.

No live behavior was activated. This change did not touch WhatsApp activation,
smoke, canary, production, SendAdapter live behavior, outbox live dispatch,
workflow side effects, action side effects, legacy deletion, staging, commit, or
worktree cleanup.

## Latest Result - Tenant Dinamo Product Agent No-Send Passed

Latest command:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:UV_CACHE_DIR='..\.uv-cache'
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED='true'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED='false'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED='false'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED='false'
uv run python ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
```

Result:

- `run_status=passed`
- Internal Test Lab decision: `TEST_LAB_PASSED`
- Final gate decision: `REAL_AGENT_TEST_LAB_NO_SEND_READY`
- `execution_mode=runtime_v2_agent_service`
- OpenAI API real: `true`
- Model: `gpt-4o-mini`
- `suite_id=a9059d97-7732-46d2-9d0b-c95bf2d73a28`
- `test_run_id=c9c9baa0-308d-4b6b-b9fb-44b39b4c2901`
- `tenant_id=5528e854-f446-46e8-bac0-bac28a8492fe`
- `agent_version_id=6d4e3937-3621-4951-b9ab-bdcd05dd1577`
- `send_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `send_decision=no_send` on every turn
- `outbound_outbox pending/retry=0` before and after
- `business_event_ledger side_effects_allowed=0` before and after
- no WhatsApp
- no smoke
- no outbox live
- no workflow/action side effects

Tenant Product Agent bindings created/verified:

- knowledge sources: 5
- tool bindings: 7
- field permissions: 11
- contract source:
  `docs/tenant_sources/dinamo/dinamo_runtime_contract.json`
- manifest source:
  `docs/tenant_sources/dinamo/dinamo_knowledge_sources_manifest.json`
- scenario source:
  `docs/tenant_sources/dinamo/dinamo_test_lab_scenarios.json`

Scenario A - negocio ambiguo:

1. `"Hola, quiero informacion del credito"`
   - final message:
     `"Sí se puede revisar; para darte el plan correcto dime cómo recibes tus ingresos."`
   - tools: none
   - state writes: none
   - pending slot: `income_type`
2. `"Tengo negocio"`
   - tool: `credit_plan.resolve:succeeded`
   - final message:
     `"Va, si tienes negocio. Para darte el plan correcto dime si estas dado de alta en SAT/RIF o si lo manejas sin comprobantes."`
   - state writes: none
   - pending slot: `business_tax_status`
3. `"Vendo comida desde mi casa"`
   - tool: `credit_plan.resolve:succeeded`
   - final message repeats the SAT/RIF vs sin comprobantes clarification
   - state writes: none
4. `"No tengo SAT"`
   - tool: `credit_plan.resolve:succeeded`
   - state writes:
     - `plan_selection=20%`
     - `down_payment_percent=20`
   - evidence: `requirements:sin_comprobantes_20`
5. `"Quiero algo economico para moverme diario"`
   - final message:
     `"Me falta saber cuánto tiempo llevas trabajando."`
6. `"La Adventure"`
   - tool: `catalog.search:succeeded`
   - state writes:
     - `product_selection=Adventure Elite 150 CC`
     - `product_catalog_id=adventure_elite_150_cc`

Scenario B - Skeleton, buró, tarjeta:

1. `"Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro"`
   - tools: `catalog.search:succeeded`, `faq.lookup:succeeded`
   - state writes:
     - `product_selection=Skeleton 400 CC`
     - `product_catalog_id=skeleton_400_cc`
   - final message:
     `"Sí se puede revisar; para darte el plan correcto dime cómo recibes tus ingresos."`
2. `"me pagan por tarjeta"`
   - tool: `credit_plan.resolve:succeeded`
   - state writes:
     - `plan_selection=10%`
     - `down_payment_percent=10`
   - final message:
     `"Perfecto, ya validé tu tipo de ingreso para el plan. ¿Cuánto tiempo llevas trabajando?"`
3. `"tengo 2 anos"`
   - tool: `quote.resolve:succeeded`
   - state writes:
     - `employment_seniority=24`
     - `quote_snapshot_id=quote-skeleton_400_cc-plan-10`
   - final message:
     `"Para Skeleton 400 CC con 10% credito, el enganche es de $8,147 y los pagos son de $3,236 por 72 quincenas. Para avanzar, dime si quieres seguir con la revisión."`
4. `"que papeles ocupo"`
   - tool: `requirements.lookup:succeeded`
   - state writes:
     - `requirements_checklist`
   - final message:
     `"Para ese plan ocupas: INE vigente por ambos lados; Comprobante de domicilio; 2 estados de cuenta recientes; Un mes de nómina dentro del estado de cuenta."`

Trace and audit:

- `universal_turn_trace` present on all 10 turns.
- policy result passed on all 10 turns.
- required tools succeeded on all turns where hard data was required.
- no required tool skipped/failed in the passed run.
- no policy failure visible.
- token usage was not emitted by the Runtime V2 AgentService trace in this run;
  the report records `estimated_cost.status=token_usage_missing` for each turn.
  This is an observability gap for cost accounting, not a send/live safety
  failure.
- API key value was not printed or written.

Verification commands:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:UV_CACHE_DIR='..\.uv-cache'
uv run ruff check atendia\agent_runtime\advisor_brain_contract.py atendia\agent_runtime\knowledge_tool_layer.py atendia\agent_runtime\advisor_pipeline.py atendia\agent_runtime\semantic_interpreter.py atendia\agent_runtime\mandatory_tools.py tests\agent_runtime\test_dinamo_income_resolution_policy.py tests\agent_runtime\test_semantic_interpreter_runtime_v2.py ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
uv run pytest tests\agent_runtime\test_dinamo_income_resolution_policy.py tests\agent_runtime\test_semantic_interpreter_runtime_v2.py tests\agent_runtime\test_product_agent_runtime_context_overlay.py -q
uv run pytest tests\product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Verification results:

- ruff: passed
- runtime focused tests: `30 passed`
- product agent tests: `153 passed`
- product agent coverage: `100%`

## Historical Failed Result - Real OpenAI + Runtime V2 AgentService No-Send

Latest command:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:UV_CACHE_DIR='..\.uv-cache'
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED='true'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED='false'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED='false'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED='false'
uv run python ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
```

Result:

- `OPENAI_API_KEY` present: `true`
- API key value was not printed or written.
- `run_status=failed`
- Internal Test Lab decision: `TEST_LAB_BLOCKED_BY_TOOL`
- Final gate decision: `REAL_AGENT_TEST_LAB_FAILED_BY_BAD_RESPONSE`
- `execution_mode=runtime_v2_agent_service`
- `send_decision=no_send` on every turn
- `outbound_outbox pending/retry=0` before and after
- `business_event_ledger side_effects_allowed=0` before and after
- no WhatsApp
- no smoke
- no outbox live
- no workflow/action side effects

This run confirms the OpenAI API blocker is closed. The Test Lab now reaches
real OpenAI through Runtime V2 `AgentService`, with DB-backed context, tenant
tools, StateWriter, Policy, trace, and `no_send` SendAdapter.

The gate is still not ready because the real agent behavior failed the scenario
contract:

- Scenario A, turn 2 `"Tengo negocio"` incorrectly executed
  `credit_plan.resolve`, wrote `plan_selection=15%` and
  `down_payment_percent=15`, and replied:
  `"Perfecto, ya validé tu tipo de ingreso para el plan. ¿Cuánto tiempo llevas trabajando?"`
- Scenario A, turns 3-6 repeatedly produced:
  `"Dime qué dato quieres revisar."`
- Scenario A, turn 4 `"No tengo SAT"` did not execute `credit_plan.resolve` and
  did not write the expected Sin Comprobantes plan fields.
- Scenario A, turn 6 `"La Adventure"` did not execute `catalog.search` and did
  not write `product_selection`.
- Scenario B, turn 3 `"tengo 2 anos"` executed `quote.resolve` and wrote
  `quote_snapshot_id`, but did not write `employment_seniority`.

Positive evidence from Scenario B:

- `"Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro"` executed
  `catalog.search` and `faq.lookup`, wrote `product_selection`, and stayed in
  `no_send`.
- `"me pagan por tarjeta"` executed `credit_plan.resolve`, wrote
  `plan_selection=10%` and `down_payment_percent=10`, and stayed in `no_send`.
- `"tengo 2 anos"` executed `quote.resolve` and produced a quote from validated
  tool data.
- `"que papeles ocupo"` executed `requirements.lookup` and wrote
  `requirements_checklist`.

New Test Lab validation added in this pass:

- Scenarios can now assert `final_message_not_contains`.
- Scenarios can now assert `forbidden_state_writes`.
- The real suite now fails if generic copy like
  `"Dime qué dato quieres revisar."` appears where the scenario forbids it.
- The real suite now fails if an ambiguous answer writes plan fields when the
  scenario requires no hard state write.

Current honest state:

- OpenAI API real: PASSED
- Runtime V2 AgentService path: PASSED
- DB-backed no-send execution: PASSED
- DB audit outbox/side effects: PASSED
- Tool/state/policy/trace evidence: PRESENT
- Scenario behavior: FAILED
- Live/smoke readiness: BLOCKED

Next technical fixes before readiness:

- Prevent generic business answers like `"Tengo negocio"` from becoming a hard
  `negocio_sat` plan without enough evidence.
- Preserve/use the pending slot across Scenario A so `"No tengo SAT"` can
  resolve Sin Comprobantes through `credit_plan.resolve`.
- Ensure product mentions like `"La Adventure"` trigger `catalog.search` from
  the contextual semantic path.
- Write explicit `employment_seniority` when the customer answers seniority and
  quote is resolved in the same turn.

## Latest Result - Runtime V2 AgentService With Product Contract

Latest command:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:UV_CACHE_DIR='..\.uv-cache'
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED='true'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED='false'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED='false'
$env:ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED='false'
uv run python ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
```

Result:

- `run_status=blocked`
- `run_decision=REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API`
- `execution_mode=runtime_v2_agent_service`
- `send_decision=no_send` on every turn
- `trace_ids` present via `universal_turn_trace.turn_id`
- `risk_flags=["semantic_interpreter_provider_error", "APIConnectionError"]`
- `outbound_outbox pending/retry=0` before and after
- `business_event_ledger side_effects_allowed=0` before and after
- no WhatsApp
- no smoke
- no outbox live
- no workflow/action side effects

What changed in this pass:

- Product Agent Test Lab no longer accepts `runtime_contract_ready=true` without
  an actual runtime contract payload.
- `ProductAgentRuntimeAdapter` now extracts a canonical
  `tenant_domain_contract` from `AgentVersion.snapshot`, `tool_policy`,
  `knowledge_policy`, `field_policy`, or `safety_policy`.
- `ContextBuilder` can apply that Product Agent contract only when the turn
  comes from `product_agent_runtime_adapter` and `send_mode=no_send`.
- The overlay does not replace an existing tenant runtime contract.
- The Test Lab runner now creates/selects a version with an explicit
  Product-First runtime contract and structured tenant source bindings.
- Added structured tenant sources under `docs/tenant_sources/dinamo/`:
  - `CatalogoMotos2026_DINAMO.json`
  - `Requisitos_Credito_Dinamo.json`
  - `FAQ_DINAMO.json`
- Test Lab now classifies semantic provider connection failures as
  `REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API` instead of hiding them behind
  generic `trace_missing`.

Why it is blocked:

- The local sandbox cannot reach OpenAI from this run.
- A direct isolated SemanticInterpreter check selected
  `ChatGPTSemanticInterpreterProvider` and failed with `APIConnectionError`.
- Because ChatGPT could not return a structured interpretation, Runtime V2
  correctly did not execute tenant tools or write validated state.

Exact generated visible message during the blocked run:

```text
Necesito que una persona del equipo revise esto para responderte con certeza.
```

This message was not sent to WhatsApp because the run stayed in no-send.

Update after Runtime V2 adapter correction:

- The old `agent_service_real` name was removed from executable code.
- The direct model path is now named `openai_direct_provider`.
- The readiness path is now named `runtime_v2_agent_service`.
- `openai_direct_provider` cannot mark publish readiness.
- `runtime_v2_agent_service` uses `ProductAgentRuntimeAdapter` and calls Runtime
  V2 `AgentService` without injecting a direct OpenAI provider.
- The adapter persists inbound sandbox messages before the turn so
  `ContextBuilder` can read DB-backed history.
- The adapter requires a Runtime V2 tenant/product contract and fails closed with
  `REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT` when it is missing.

## Implemented

- Added `execution_mode` to Test Lab run payload:
  - `simulated_contract`
  - `openai_direct_provider`
  - `runtime_v2_agent_service`
- model-backed modes require `mode=no_send`.
- model-backed modes enforce:
  - max 2 scenarios
  - max 6 turns per scenario
  - max 350 output tokens per turn
  - temperature 0.2
- Test Lab constructs an OpenAI provider explicitly only for
  `openai_direct_provider`.
- Runtime readiness uses `runtime_v2_agent_service` through
  `ProductAgentRuntimeAdapter`.
- Mock or safe fallback providers block the run with
  `REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API`.
- Required tool skipped/failed blocks the run.
- Policy failed/blocked blocks the run.
- Turn evidence now includes:
  - execution mode
  - token usage
  - estimated cost object
  - failure reason
- OpenAI provider now supports optional `temperature`, `max_output_tokens`, and
  response usage capture.
- Product Agent Builder UI now shows:
  - execution mode selector
  - `OpenAI API real, WhatsApp no-send` warning
  - token totals
  - token usage per turn
  - estimated cost per turn

## Verification

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run ruff check atendia/product_agents atendia/agent_runtime/model_provider.py tests/product_agents tests/agent_runtime/test_agent_model_provider_v2.py
```

Result:

- `All checks passed!`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Result:

- `137 passed`
- `Required test coverage of 100% reached. Total coverage: 100.00%`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run pytest tests/agent_runtime/test_agent_model_provider_v2.py -q
```

Result:

- `20 passed`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder
```

Result:

- `Checked 3 files`
- `No fixes applied`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include=src/features/product-agent-builder/components/AgentBuilderPage.tsx --coverage.thresholds.statements=100 --coverage.thresholds.branches=100 --coverage.thresholds.functions=100 --coverage.thresholds.lines=100
```

Result:

- `25 passed`
- Statements: `100%`
- Branches: `100%`
- Functions: `100%`
- Lines: `100%`

## OpenAI Direct Provider Execution

Executed with OpenAI API real in DB-backed Test Lab direct-provider mode, always
in `no_send`. This run is retained as diagnostic evidence only; it cannot mark
readiness.

Command:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'
uv run python ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
```

Key handling:

- `OPENAI_API_KEY` present: `true`
- Key length recorded: `164`
- Key value was not printed.

Runtime flags:

- `send_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `model_provider=openai`
- `model=gpt-4o-mini`

DB identifiers:

- `tenant_id=5528e854-f446-46e8-bac0-bac28a8492fe`
- `agent_version_id=74fceba9-e559-40a3-a65f-5c0129c71800`
- `suite_id=c3f0fd2e-d82f-487a-b9d2-93d07822ee3c`
- `test_run_id=d36ca115-cd33-40fc-a9ea-5ce78956f954`

Previous OpenAI direct run result:

- Internal Test Lab status: `failed`
- Internal Test Lab decision: `TEST_LAB_BLOCKED_BY_TRACE`
- Final gate decision: `REAL_AGENT_TEST_LAB_FAILED_BY_BAD_RESPONSE`

The run reached OpenAI and generated customer-facing drafts, but it did not load
the tenant contract/tools/trace path expected for Product-First readiness. The
responses were generic ChatGPT-style answers, no required tools were requested,
no tools executed, no state writes occurred, and every turn missed trace IDs.

## Runtime V2 AgentService Execution

Executed again after replacing the readiness path with
`runtime_v2_agent_service`.

Command:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
$env:PYTHONPATH='.'
$env:ATENDIA_V2_DATABASE_URL='postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2'
uv run python ..\tools\run_real_agent_test_lab_no_send_2026_06_07.py
```

Runtime flags:

- `send_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`
- `model_provider=openai`
- `model=gpt-4o-mini`

DB identifiers:

- `tenant_id=5528e854-f446-46e8-bac0-bac28a8492fe`
- `agent_version_id=74fceba9-e559-40a3-a65f-5c0129c71800`
- `suite_id=868a7ced-2ad6-49fc-a2d4-f4731ba53d14`
- `test_run_id=fbed6bd0-f20c-40d5-bdba-17f68160f97d`

Run result:

- Internal Test Lab status: `blocked`
- Internal Test Lab decision: `REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT`
- Final gate decision: `REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT`

The run no longer fell through to generic OpenAI. It entered the Runtime V2
Test Lab adapter and failed closed before model execution because the selected
Product Agent / tenant does not have a Runtime V2 contract available to the
adapter. This is the intended behavior for a missing runtime contract.

Per-turn evidence:

- `execution_mode=runtime_v2_agent_service`
- `send_decision=no_send`
- `final_message=null`
- `trace_id=null`
- `tools_required=[]`
- `tools_executed=[]`
- `state_writes=[]`
- `policy_result.status=failed`
- `errors[0].where=product_agent_runtime_adapter`
- `errors[0].code=runtime_contract_missing`
- `estimated_cost.status=token_usage_missing`

Coverage summary:

- `runtime_v2_agent_service=true`
- `readiness_eligible=true`
- max scenarios: `2`
- max turns per scenario: `6`
- max output tokens: `350`
- temperature: `0.2`

DB audit for the Runtime V2 run:

- before: `outbound_outbox pending/retry = 0`
- before: `business_event_ledger side_effects_allowed = 0`
- after: `outbound_outbox pending/retry = 0`
- after: `business_event_ledger side_effects_allowed = 0`

## Scenario A - Negocio ambiguo

Input turns:

1. `Hola, quiero informacion del credito`
2. `Tengo negocio`
3. `Vendo comida desde mi casa`
4. `No tengo SAT`
5. `Quiero algo economico para moverme diario`
6. `La Adventure`

Generated messages:

1. `Hola, ¿qué tipo de información sobre el crédito necesitas? Puedo ayudarte con detalles sobre requisitos, tasas de interés, o el proceso de solicitud.`
2. `¿Podrías darme más detalles sobre tu negocio? Así podré ayudarte mejor.`
3. `¿Te gustaría saber cómo puedes formalizar tu negocio de venta de comida desde casa o necesitas información específica sobre algún aspecto en particular?`
4. `Entiendo que no tienes un SAT. ¿Te gustaría saber más sobre cómo obtener uno o sobre alternativas disponibles?`
5. `Para moverte de manera económica a diario, podrías considerar opciones como el transporte público, bicicletas compartidas o scooters eléctricos. Si necesitas más información sobre alguna de estas opciones o si hay servicios específicos en tu área, házmelo saber.`
6. `Parece que mencionaste "La Adventure". ¿Te gustaría saber más sobre esta aventura o necesitas información específica relacionada con ella?`

Validation:

- Expected: do not assume plan on `Tengo negocio`; ask SAT/RIF vs sin
  comprobantes; resolve `No tengo SAT` through knowledge/tool; recommend by use;
  validate Adventure with `catalog.search`; quote with `quote.resolve` only when
  plan/model are validated.
- Actual: no plan resolution, no tenant knowledge, no catalog validation, no
  quote, no trace.
- Tools: none requested/executed.
- State writes: none.
- Policy: passed.
- Send decision: `no_send` on every turn.
- Trace IDs: missing on every turn.
- Token usage: input `6737`, output `431`, total `7168`.

## Scenario B - Skeleton / buro / tarjeta

Input turns:

1. `Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro`
2. `me pagan por tarjeta`
3. `tengo 2 anos`
4. `que papeles ocupo`

Generated messages:

1. `Para poder darte un precio a crédito de la Skeleton, necesito un snapshot de la cotización o información adicional sobre el modelo específico que estás interesado. Además, estar en buró puede afectar las opciones de crédito disponibles. ¿Tienes algún detalle más sobre el modelo o la cotización que viste?`
2. `¿Podrías aclarar si te refieres a que recibes pagos a través de tarjeta de crédito o débito?`
3. `Parece que mencionaste que tienes 2 años. ¿Hay algo específico sobre tu edad o situación que te gustaría discutir?`
4. `Para poder ayudarte mejor, necesitaría saber a qué tipo de trámite o proceso te refieres. ¿Estás buscando información sobre documentos para un trámite específico?`

Validation:

- Expected: `catalog.search` for Skeleton, `faq.lookup` for buro,
  `credit_plan.resolve` for `me pagan por tarjeta`, antiguedad write for
  `tengo 2 anos`, `quote.resolve`, and `requirements.lookup`.
- Actual: no tools requested/executed; no state writes; generic responses.
- Tools: none requested/executed.
- State writes: none.
- Policy: passed.
- Send decision: `no_send` on every turn.
- Trace IDs: missing on every turn.
- Token usage: input `4520`, output `316`, total `4836`.

## Token And Cost Evidence

- Total input tokens: `11257`
- Total output tokens: `747`
- Total tokens: `12004`
- Estimated cost: not calculated by code because no configured model rate exists.
  Evidence status: `cost_rate_not_configured`.

## DB Audit

Before run:

- `outbound_outbox pending/retry = 0`
- `business_event_ledger side_effects_allowed = 0`

After run:

- `outbound_outbox pending/retry = 0`
- `business_event_ledger side_effects_allowed = 0`

The run created Test Lab evidence records and sandbox conversations/messages,
but no live outbox, WhatsApp send, workflow side effects, or action side effects.

Post-run confirmation:

```sql
select count(1) as outbound_outbox_pending_retry
from outbound_outbox
where tenant_id='5528e854-f446-46e8-bac0-bac28a8492fe'
  and status in ('pending','retry');
```

Result: `0`

```sql
select count(1) as business_event_ledger_side_effects_allowed
from business_event_ledger
where tenant_id='5528e854-f446-46e8-bac0-bac28a8492fe'
  and side_effects_allowed=true;
```

Result: `0`

Post-run flags:

- `send_enabled=false`
- `actions_enabled=false`
- `workflow_events_enabled=false`

## Fixes Applied During Real Runs

The real DB-backed runner exposed a real schema mismatch: sandbox system
messages inserted by Test Lab did not set `messages.sent_at`, but the real DB
requires it. Fixed in `core/atendia/product_agents/test_lab.py` by setting
`sent_at=now()` for Test Lab sandbox system messages.

Runtime V2 adapter correction:

- Added `core/atendia/product_agents/runtime_adapter.py`.
- Updated `core/atendia/product_agents/test_lab.py` with
  `openai_direct_provider` and `runtime_v2_agent_service`.
- Updated `core/atendia/product_agents/service.py` so only
  `runtime_v2_agent_service` can mark Test Lab readiness.
- Updated Product Agent Builder UI to distinguish the diagnostic direct provider
  from the Runtime V2 readiness path.

Verification after the fix:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run ruff check atendia/product_agents tests/product_agents
```

Result: `All checks passed!`

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Result:

- `137 passed`
- `Required test coverage of 100% reached. Total coverage: 100.00%`

Additional verification after Runtime V2 adapter correction:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run ruff check atendia/product_agents tests/product_agents
```

Result: `All checks passed!`

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Result:

- `145 passed`
- `Required test coverage of 100% reached. Total coverage: 100.00%`

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder
```

Result:

- `Checked 3 files`
- `No fixes applied`

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include=src/features/product-agent-builder/components/AgentBuilderPage.tsx --coverage.thresholds.statements=100 --coverage.thresholds.branches=100 --coverage.thresholds.functions=100 --coverage.thresholds.lines=100
```

Result:

- `25 passed`
- Statements: `100%`
- Branches: `100%`
- Functions: `100%`
- Lines: `100%`

## Safety Confirmation

- No WhatsApp activation.
- No smoke activation.
- No live SendAdapter change.
- No outbox live dispatch.
- No workflow/action side effects.
- No canary.
- No production opening.
- No staging.
- No commit/stage.
- No Dinamo/contact hardcode introduced in Product-First shared runtime.

## Next Gate

Next step: configure or publish a Runtime V2 tenant/product contract for the
selected Product Agent version so `runtime_v2_agent_service` can proceed into
ContextBuilder, SemanticAdvisorBrain, TenantKnowledgeToolLayer, StateWriter,
Policy, universal trace, and SendAdapter no-send.

Then rerun the same maximum 2-scenario / 6-turn-per-scenario no-send suite.
Only after at least one complete scenario has trace IDs, required tools,
validated state writes where applicable, good final messages,
`send_decision=no_send`, and DB audit zero can the decision advance to
`REAL_AGENT_TEST_LAB_RUNTIME_V2_READY`.

## Final Decision

`REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT`

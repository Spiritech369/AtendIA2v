# Workflow Bridge Post-Turn Preview

Fecha: 2026-06-05

Decision: `WORKFLOW_BRIDGE_POST_TURN_PREVIEW_READY`

## Alcance

Se integro `workflow_gated_bridge` como preview post-turn usando solo eventos estructurados ya presentes en `TurnOutput.trace_metadata["business_events"]` o en `TurnOutput.trace_metadata["universal_turn_trace"]["business_events"]`.

La ruta implementada no ejecuta workflows reales, no ejecuta actions, no escribe outbox, no programa followups reales, no dispara handoff real y no envia WhatsApp. Si se entrega una sesion DB, solo registra el evento en `business_event_ledger` de forma idempotente y guarda el resultado de preview para trazabilidad.

## Archivos creados o modificados

- `core/atendia/agent_runtime/post_turn_executor.py`
- `core/atendia/agent_runtime/workflow_bridge.py`
- `core/tests/agent_runtime/test_workflow_gated_bridge.py`
- `reports/workflow_bridge_post_turn_preview.md`
- `reports/workflow_bridge_post_turn_preview.json`

## Contrato post-turn

Entrada:

- `TurnOutput`
- `TurnContext`
- `AsyncSession | None`

Flujo:

1. Leer `business_events` del trace.
2. Validar cada item como `BusinessEvent`.
3. Si hay DB, insertar en `business_event_ledger` con `side_effects_allowed=false`.
4. Si el evento ya existe, devolver resultado `duplicate`.
5. Evaluar `workflow_gated_bridge` con flags de preview.
6. Reemplazar `workflow_results` del trace con resultados del bridge.
7. Sincronizar `universal_turn_trace.workflow_results` si el bloque ya existe.

## Flags de seguridad

El preview usa:

- `actions_enabled=false`
- `workflow_side_effects_enabled=false`
- `workflow_events_enabled=true`
- `tenant_workflows_enabled=false`
- `allow_test_execution=false`

Por diseno, todo resultado queda en uno de estos estados seguros:

- `dry_run`
- `blocked`
- `not_configured`
- `duplicate`

`executed` queda siempre `false` en el helper post-turn.

## Ledger e idempotencia

El ledger mantiene la unicidad por:

`tenant_id + conversation_id + event_type + idempotency_key`

Estados nuevos en el resultado de preview:

- `ledger_status=inserted`: el evento fue registrado y consumido por el bridge.
- `ledger_status=duplicate`: el evento ya existia y no se vuelve a insertar.
- `ledger_status=not_available`: no se entrego sesion DB o no se encontro fila.

## Integracion con universal_turn_trace

El helper `attach_workflow_bridge_results_to_trace(..., replace=true)` reemplaza los resultados preliminares con el resultado real del preview post-turn.

Si el trace ya contiene `universal_turn_trace`, tambien actualiza:

`trace_metadata["universal_turn_trace"]["workflow_results"]`

## Garantias de no side effects

No se llama al workflow engine.
No se llama al executor de actions.
No se escriben mensajes.
No se escribe outbox.
No se crean followups.
No se crea handoff real.
No se activa WhatsApp.
No se aplica config live.

## Comandos ejecutados

- `uv run ruff check atendia/agent_runtime/post_turn_executor.py atendia/agent_runtime/workflow_bridge.py tests/agent_runtime/test_workflow_gated_bridge.py`
- `uv run pytest tests/agent_runtime/test_workflow_gated_bridge.py -m "not integration_db" -q`
- `docker compose -f docker-compose.test.yml up -d postgres-test`
- `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime/test_workflow_gated_bridge.py tests/agent_runtime/test_business_event_ledger.py -m "integration_db" -q`
- `uv run pytest tests/agent_runtime/test_workflow_gated_bridge.py tests/agent_runtime/test_business_event_ledger.py tests/agent_runtime/test_business_events.py tests/agent_runtime/test_universal_turn_trace.py -m "not integration_db" -q`
- `uv run pytest tests/agent_runtime/test_dinamo_shadow_e2e.py -q`
- `uv run pytest tests/agent_runtime -m "not integration_db" -q`
- `docker compose -f docker-compose.test.yml down`

## Resultados exactos

- Ruff enfocado: `All checks passed!`
- Bridge no-DB: `12 passed, 5 deselected`
- Bridge + ledger integration DB: `9 passed, 13 deselected`
- Bateria enfocada no-DB: `35 passed, 9 deselected`
- Dinamo shadow E2E: `4 passed`
- Agent runtime no-DB: `214 passed, 43 deselected`

Warnings observados:

- `PytestCacheWarning` por permisos de `.pytest_cache`.
- `UserWarning` preexistente: `Tone.register` shadow en `atendia/contracts/tone.py`.

## Riesgos restantes

- Esta fase no conecta el helper a un runner live; queda como funcion post-turn segura y testeada.
- Si un caller entrega eventos invalidos, se omiten y se registra warning.
- La ejecucion real de workflows sigue deliberadamente no implementada en esta ruta.

## Siguiente paso recomendado

Conectar el helper desde el punto post-turn del runtime v2 que ya tenga el `TurnOutput` con `universal_turn_trace`, manteniendo los mismos flags apagados en shadow/canary antes de considerar cualquier habilitacion real por tenant.

# Universal Trace API Bridge

Decision final: `UNIVERSAL_TRACE_API_BRIDGE_READY`

## Alcance

Se valido y cerro el puente real entre backend `universal_turn_trace` y frontend tenant-aware sin activar trafico real, sin enviar WhatsApp, sin aplicar configuracion Dinamo a produccion y sin habilitar actions/workflows reales.

## Endpoints revisados

- `GET /api/v1/turn-traces`
  - Lista metadata de traces. No se modifica porque no debe cargar payloads completos.
- `GET /api/v1/turn-traces/{trace_id}`
  - Endpoint corregido. Ahora agrega `trace_metadata` al detalle y preserva `composer_output`, `state_after`, `raw_llm_response`, `tool_calls` y el shape previo.
- `GET /api/v1/turn-traces/{trace_id}/why-answer-v2`
  - Revisado. Sigue usando el agregador actual y no se modifica.
- `POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/preview`
  - Revisado. Ya devuelve `output.trace_metadata` directo.
- `POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/send`
  - Revisado. Persiste `TurnOutput.model_dump(mode="json")` en `turn_traces.composer_output`, donde vive `trace_metadata`.
- `GET /api/v1/conversations/{conversation_id}`
  - Revisado para impacto en ContactPanel. No se modifica en esta tarea; el puente requerido para `universal_turn_trace` vive en `turn-traces/{id}`.
- `GET /api/v1/conversations/{conversation_id}/messages`
  - Revisado. No transporta universal trace.

## Shape antes

`GET /api/v1/turn-traces/{trace_id}` devolvia payloads como:

```json
{
  "composer_output": {
    "trace_metadata": {
      "universal_turn_trace": {}
    }
  },
  "state_after": {},
  "raw_llm_response": "...",
  "tool_calls": []
}
```

Pero no exponia `trace_metadata` en top-level, asi que el frontend dependia de fallbacks anidados o caia a `metadata_missing/raw trace`.

## Shape despues

El detalle de trace ahora incluye:

```json
{
  "trace_metadata": {
    "universal_turn_trace": {
      "trace_version": "1.0",
      "gpt_proposed": {},
      "atendia_validation": {},
      "mandatory_tool_decisions": [],
      "state_changes": {},
      "guards": [],
      "final_output": {
        "final_message": "mensaje final"
      }
    }
  },
  "composer_output": {
    "trace_metadata": {}
  },
  "raw_llm_response": "..."
}
```

La extraccion es aditiva y sin migracion DB:

1. `composer_output.trace_metadata`
2. `state_after.trace_metadata`
3. `raw_llm_response` parseado como JSON si contiene `trace_metadata`
4. `universal_turn_trace` directo, envuelto como `{"universal_turn_trace": ...}`

Si no existe metadata, el endpoint devuelve `trace_metadata: null`.

## Archivos modificados

- `core/atendia/api/turn_traces_routes.py`
- `core/tests/api/test_turn_traces_routes.py`
- `frontend/tests/features/turn-traces/UniversalTracePanel.test.tsx`

## Archivos creados

- `core/tests/api/test_turn_trace_metadata_serializer.py`
- `reports/universal_trace_api_bridge.md`
- `reports/universal_trace_api_bridge.json`

## Frontend consumption

`readUniversalTurnTrace` ya leia `trace.trace_metadata.universal_turn_trace`. Se agrego un test con shape real de `TurnTraceDetail` para confirmar que:

- prioriza `trace_metadata.universal_turn_trace` top-level
- renderiza el dominio correcto (`appointment_services`)
- no cae a trazas anidadas equivocadas
- si falta universal trace, `UniversalTracePanel` muestra `metadata_missing` y conserva el camino de raw/debug

## Tests ejecutados

- `ATENDIA_V2_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2 uv run pytest tests/agent_runtime/test_universal_turn_trace.py tests/api/test_turn_traces_routes.py -q`
  - Resultado: `21 passed, 2 warnings in 18.41s`
- `uv run pytest tests/agent_runtime/test_universal_turn_trace.py tests/api/test_turn_trace_metadata_serializer.py -q`
  - Resultado: `13 passed, 2 warnings in 0.11s`
- `uv run ruff check atendia/api/turn_traces_routes.py tests/api/test_turn_trace_metadata_serializer.py tests/api/test_turn_traces_routes.py`
  - Resultado: `All checks passed!`
- `uv run pytest tests/agent_runtime -m "not integration_db" -q`
  - Resultado: `179 passed, 27 deselected, 2 warnings in 2.89s`
- `npm exec -- vitest run tests/features/turn-traces/UniversalTracePanel.test.tsx tests/features/conversations/TenantFieldPanel.test.tsx`
  - Resultado: `Test Files 2 passed (2)`, `Tests 11 passed (11)`, duration `3.23s`
- `npm run typecheck`
  - Resultado: `tsc --noEmit` passed
- `npm exec -- biome check src/features/turn-traces/api.ts src/features/turn-traces/lib/universalTrace.ts src/features/turn-traces/components/UniversalTracePanel.tsx tests/features/turn-traces/UniversalTracePanel.test.tsx tests/features/conversations/TenantFieldPanel.test.tsx`
  - Resultado: `Checked 5 files in 27ms. No fixes applied.`
- `git diff --check -- <archivos de la tarea>`
  - Resultado: sin errores de whitespace. Solo warnings Git de LF/CRLF.

Nota de entorno: el primer intento del comando API uso la URL por defecto `localhost:5432` y fallo con `ConnectionRefusedError [WinError 1225]`. Se confirmo que el Postgres local disponible estaba en `localhost:5433` (`atendia_postgres_v2`, healthy) y se re-ejecuto exitosamente con `ATENDIA_V2_DATABASE_URL`.

## Riesgos restantes

- La configuracion local por defecto apunta a `localhost:5432`, mientras el contenedor activo expone `5433`; conviene alinear `.env`/docs de test para evitar falsos negativos.
- `GET /api/v1/conversations/{id}` aun no expone un `tenant_domain_contract` top-level desde backend; no bloquea este puente de trace, pero conviene revisarlo para completar metadata declarativa de ContactPanel.
- Traces legacy sin `trace_metadata` seguiran devolviendo `null`, como fallback seguro.

## Siguiente paso recomendado

Alinear la URL de DB de test/dev y revisar en una tarea separada si `ConversationDetail` debe exponer `tenant_domain_contract` top-level para que ContactPanel no dependa solo de `customer_fields`.

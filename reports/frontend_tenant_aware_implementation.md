# Frontend Tenant-Aware Implementation

Decision final: `FRONTEND_TENANT_AWARE_READY`

## Alcance

Se implemento Prompt 5 para que el frontend operativo renderice campos por metadata declarativa del tenant y explique cada turno desde `universal_turn_trace`, sin activar trafico real, sin aplicar configuracion Dinamo a DB, sin habilitar actions/workflows reales y sin hardcodear Dinamo en los componentes runtime nuevos.

## Archivos creados

- `frontend/src/features/conversations/components/TenantFieldPanel.tsx`
- `frontend/src/features/turn-traces/components/DecisionTimeline.tsx`
- `frontend/src/features/turn-traces/components/ToolCards.tsx`
- `frontend/src/features/turn-traces/components/GuardCards.tsx`
- `frontend/src/features/turn-traces/components/StateWriterCards.tsx`
- `frontend/src/features/turn-traces/components/PipelineCard.tsx`
- `frontend/src/features/turn-traces/components/BusinessEventCards.tsx`
- `frontend/src/features/turn-traces/components/UniversalTracePanel.tsx`
- `frontend/src/features/turn-traces/lib/universalTrace.ts`
- `frontend/tests/fixtures/universalTurnTrace.ts`
- `frontend/tests/features/conversations/TenantFieldPanel.test.tsx`
- `frontend/tests/features/turn-traces/UniversalTracePanel.test.tsx`

## Archivos modificados

- `frontend/src/features/conversations/api.ts`
- `frontend/src/features/conversations/components/ContactPanel.tsx`
- `frontend/src/features/conversations/components/DebugPanel.tsx`
- `frontend/src/features/turn-traces/api.ts`
- `frontend/src/features/turn-traces/components/TurnTraceInspector.tsx`

## Render de tenant metadata

`ContactPanel` normaliza `conversation.customer_fields` con `normalizeTenantFields` y renderiza `TenantFieldPanel` cuando hay metadata declarativa: `field key`, `label`, `group`, `domain_role`, `display_format`, `value`, `status`, `source`, `writer`, `confidence`, `last_trace_id` y `evidence_refs`.

Si existe `tenant_domain_contract` pero faltan campos declarativos, el panel muestra `metadata_missing`, respeta `safe_mode` cuando venga del contrato y solo muestra datos basicos: etapa, fuente, telefono y email. La ruta legacy con aliases/campos canonicos antiguos queda limitada a conversaciones sin `tenant_domain_contract`, para preservar compatibilidad sin hacer asumir Dinamo a tenants declarativos.

## Render de universal_turn_trace

`readUniversalTurnTrace` lee la traza desde `trace_metadata.universal_turn_trace` y tambien soporta ubicaciones anidadas legacy en `composer_output.trace_metadata` y `state_after.trace_metadata`.

`UniversalTracePanel` agrega una vista no tecnica de "Por que respondio asi" y compone:

- `DecisionTimeline`: mensaje del cliente, entendimiento GPT, propuesta GPT, tools obligatorias, tools, StateWriter, guards, lifecycle, workflows/eventos y `final_output.final_message`.
- `ToolCards`: tool id, obligatoriedad, razon, status, inputs seguros, output estructurado, usos, citas, tenant y error/no-data.
- `StateWriterCards`: accepted, blocked, needs_review e invalidated fields.
- `GuardCards`: guard id, scope, result, reason, affected items, evidence refs y next step.
- `PipelineCard`: etapa/status actual, propuesta GPT, validacion AtendIA, transition y reason.
- `BusinessEventCards`: eventos/workflows con estados emitted, blocked, dry-run y executed.

## Estados visuales

`TenantFieldPanel` distingue:

- `validated`
- `proposed`
- `needs_review`
- `rejected`
- `blocked`

Los campos propuestos por GPT no se muestran como `validated`; solo los datos aceptados/validados por AtendIA reciben ese estado.

## Fixtures

- Fixture `vehicleCreditFields` y `vehicleUniversalTrace`: simula dominio `vehicle_credit_sales` con seleccion, plan, papeleria, buro, handoff, tool faltante, guard blocked y final message de `TurnOutput.final_message`.
- Fixture `appointmentFields` y `appointmentUniversalTrace`: simula `appointment_services` con servicio, horario y estado de cita. Los tests validan que no aparezcan campos de moto, plan credito, papeleria ni quote snapshot.

## Comandos ejecutados

- `npm exec -- vitest run tests/features/conversations/TenantFieldPanel.test.tsx tests/features/turn-traces/UniversalTracePanel.test.tsx`
  - Resultado final: `Test Files 2 passed (2)`, `Tests 10 passed (10)`, duration `2.67s`.
- `npm run typecheck`
  - Resultado: passed, `tsc --noEmit` sin errores.
- `npm exec -- biome check <17 archivos tocados>`
  - Resultado final: `Checked 17 files in 84ms. No fixes applied.`
- `npm run lint`
  - Resultado: failed por deuda global del frontend fuera del alcance. Biome reporto `Checked 241 files`, `Found 309 errors`, `38 warnings`, `21 infos`, con muchos problemas de formato/CRLF en archivos existentes como `biome.json`, `package.json`, `playwright.config.ts`, `src/api/ws-client.ts` y otros.
- `uv run pytest tests/agent_runtime -m "not integration_db" -q`
  - Resultado: `179 passed, 27 deselected, 2 warnings in 1.98s`.
- `rg -n "Dinamo|DINAMO|vehicle_credit_sales|Moto seleccionada|Papeler|Buró|Buro|Cotización validada|Cotizacion validada" frontend/src/features/conversations/components frontend/src/features/turn-traces`
  - Resultado: sin matches en componentes runtime.

## Riesgos restantes

- El backend debe exponer `customer_fields` con metadata declarativa y `trace_metadata.universal_turn_trace`; si falta, la UI cae en `metadata_missing` o raw trace.
- La ruta legacy sin `tenant_domain_contract` conserva compatibilidad con campos canonicos antiguos. Los tenants con contrato declarativo no usan esa ruta.
- `npm run lint` completo sigue fallando por deuda global/preexistente del frontend; los archivos tocados pasan Biome enfocado.

## Siguiente paso recomendado

Revisar el shape real del endpoint de traces para asegurar que persiste y retorna `trace_metadata.universal_turn_trace` en produccion/sandbox antes de activar cualquier trafico real.

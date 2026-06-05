# Dinamo Live Smoke Failure Diagnosis

Generated: 2026-06-05

## Scope

Solo diagnostico. No se activo trafico nuevo, no se envio WhatsApp desde esta auditoria, no se modifico config live y no se aplico fix productivo.

## Conversacion auditada

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id observado en traces: `c169deec-226d-55b7-bd07-270f339e75a6`
- conversation_id: `a2b48d30-623f-4502-8fd3-df55d265d194`
- contact/customer_id: `05da6577-2647-4b79-ae24-2d233a22bbd3`
- channel: `whatsapp_meta`
- tenant config relevante: `agent_runtime_v2.runtime_v2_enabled=true`, pero `rollout_mode=preview_only`, `send_enabled=false`, `outbox_enabled=false`, `actions_enabled=false`, `shadow_mode_enabled=false`.
- universal_turn_trace: ausente en todos los turnos auditados.

## Runtime por turno

| Turno | Inbound | Trace id | Runtime / salida | Evidencia |
| --- | --- | --- | --- | --- |
| 6 | `hola me interesa credito` | `fe055c47-4abf-436a-855c-e4c9ff6cc213` | legacy `ConversationRunner` con `composer_provider=fallback` | `nlu_error:APIConnectionError`, `ComposerProviderError`, outbox `out:...:6:0` |
| 7 | `rayo elite` + `hola me interesa credito` en burst | `35142ed7-0f43-43b1-b02b-37d7a5b93ea9` | legacy runner con `composer_provider=openai`; copia visible tipo fallback | actualizo `Moto`, pero respondio intermitencia |
| manual | recovery posterior | sin trace normal | outbox manual | `manual-recovery:...`, texto "Va, ya tengo el modelo Rayo Elite..." |
| 8 | `me pagan en efectivo` | `63f51d19-cd18-4397-8450-93dc06351020` | legacy `ConversationRunner` con `composer_provider=fallback` | `nlu_error:APIConnectionError`, `ComposerProviderError`, pidio modelo |
| manual | `comando` | sin trace asociado | outbox manual | `manual-recovery-docs:...`, pidio INE/domicilio antes de cotizar |
| 9 | `pero cuanto es` | `c543fd1b-9bff-4999-8433-515df041a4ad` | legacy `ConversationRunner` con `composer_provider=fallback` | `nlu_error:APIConnectionError`, `ComposerProviderError`, dijo que faltaba modelo/plan |

El primer trace de la conversacion (`1d2f310c-2a09-4345-9209-3e8d0645f57e`) registro `router_trigger=legacy_runner_disabled_for_v2`, pero los turnos live posteriores fueron procesados por la ruta legacy/fallback, no por `agent_runtime_v2` con `TurnOutput.final_message`.

## State visible vs state consumido

Campos visibles / tenant-scoped para el cliente:

| Campo UI | Valor | Fuente DB |
| --- | --- | --- |
| `Moto` | `rayo elite` | `customer_field_values`, `conversation_state.extracted_data` |
| `Plan_Credito` | `Sin Comprobantes` | `customer_field_values`, `conversation_state.extracted_data` |
| `Plan_Enganche` | `20` | `customer_field_values` |
| `Cumple_Antiguedad` | `null` | campo faltante |
| `Cotizacion_Enviada` | `null` | campo faltante |
| `Ultima_Cotizacion` | `null` | campo faltante |

En turnos 8 y 9, `composer_input.extracted_data` si contenia `Moto`, `Plan_Credito`, `CREDITO` y `ENGANCHE`. Pero la politica legacy construyo:

```json
{"model": null, "income_type": "Sin Comprobantes", "plan": "20%", "quote_mode": null}
```

Causa directa: `_commercial_state` lee `MOTO` para modelo y `CREDITO`/`ENGANCHE` para plan legacy. No mapea `Moto -> model`, `Plan_Credito -> income_type` ni `Plan_Enganche -> plan` de forma canonica. El Composer ve datos tenant, pero el gate de decision legacy los interpreta con aliases viejos.

## Causa raiz principal

`LIVE_SMOKE_BLOCKED_MULTIPLE_CAUSES`

La causa principal es combinada:

- `LEGACY_RUNNER_USED`: live salio por `ConversationRunner` legacy/fallback, no por runtime v2 send.
- `RUNTIME_V2_NOT_ACTIVE`: tenant tenia v2 solo en preview, con send/outbox/actions desactivados.
- `FIELD_ALIAS_MISMATCH`: campos UI `Moto/Plan_Credito/Plan_Enganche` no alimentaron correctamente el `commercial_state` legacy.
- `FALLBACK_VISIBLE_TO_CUSTOMER`: errores de provider se convirtieron en mensajes visibles de intermitencia.
- `REQUIREMENTS_ROUTED_TOO_EARLY`: documentos salieron por manual recovery antes de cotizacion.

## Causas por fallo

| Fallo | Clasificacion |
| --- | --- |
| Ignora Moto validada | `FIELD_ALIAS_MISMATCH`, `COMPOSER_STATE_MISMATCH` |
| Ignora plan validado | `FIELD_ALIAS_MISMATCH`; `Plan_Credito` existe, pero legacy usa `CREDITO`/`ENGANCHE` |
| Pide documentos antes de cotizar | `REQUIREMENTS_ROUTED_TOO_EARLY`, fuente `manual_recovery_after_missing_documents_fallback_fix` |
| No pregunta antiguedad | `QUOTE_PRECONDITION_WRONG`; legacy agrega `no_ask_antiguedad_for_sin_comprobantes_20` aunque `Cumple_Antiguedad` falta |
| `me pagan en efectivo` no desambigua | `CASH_CREDIT_MODE_MISMATCH`; se escribio `Sin Comprobantes` en vez de preguntar recibos vs por fuera |
| `comando` no cambia modelo | `CATALOG_CHANGE_NOT_APPLIED`; no hay `turn_trace`, `catalog.search` ni invalidacion de quote |
| `pero cuanto es` no cotiza | `QUOTE_PRECONDITION_WRONG` + `FIELD_ALIAS_MISMATCH`; `model=null` en commercial_state |
| fallback visible | `PROVIDER_ERROR` + `FALLBACK_VISIBLE_TO_CUSTOMER` |
| StateWriter no aplica a live | `STATEWRITER_NOT_APPLIED_TO_LIVE`; no hay `action_execution_logs`, ni universal trace, ni decisiones v2 |

## Por que fallback fue visible

Los traces 6, 8 y 9 tienen `composer_provider=fallback`, errores `nlu_error:APIConnectionError` y `composer failed; structured safe fallback emitted`. Esos mensajes quedaron en `outbound_outbox` como `sent`, con texto visible al cliente. No hubo guard v2 que convirtiera el fallo en no-send, handoff silencioso o `needs_human` sin copia robotica.

## Por que pidio documentos antes de precio

El mensaje de documentos no corresponde a un `turn_trace` normal. En `outbound_outbox` aparece con idempotency key `manual-recovery-docs:529bf73d-14e6-4d32-8d2b-679ec33ecdf8` y metadata `manual_recovery_after_missing_documents_fallback_fix`. Eso uso requisitos de `Plan_Credito=Sin Comprobantes` y `Plan_Enganche=20` sin validar `Cotizacion_Enviada`/`Ultima_Cotizacion`, por eso salto a INE/domicilio antes de precio.

## Test regresivo creado

Archivo: `core/tests/architecture/test_dinamo_live_state_mismatch_regression.py`

Incluye dos reproducciones anonimizadas marcadas `xfail(strict=True)`:

- price request con `Moto`, `Plan_Credito`, `Plan_Enganche` debe cotizar y no pedir modelo/documentos.
- `me pagan en efectivo` debe desambiguar recibos vs por fuera y no guardar plan directamente.

Verificacion ejecutada:

```text
uv run pytest tests/architecture/test_dinamo_live_state_mismatch_regression.py -q
2 xfailed, 2 warnings
```

## Archivos creados/modificados

- `core/tests/architecture/test_dinamo_live_state_mismatch_regression.py`
- `reports/dinamo_live_smoke_failure_diagnosis.md`
- `reports/dinamo_live_smoke_failure_diagnosis.json`

## Decision final

`LIVE_SMOKE_BLOCKED_MULTIPLE_CAUSES`

## Siguiente fix recomendado

Prompt recomendado:

```text
Aplicar fix enfocado para el live smoke Dinamo: desactivar cualquier manual recovery customer-visible de documentos antes de cotizacion; mapear campos tenant `Moto/Plan_Credito/Plan_Enganche/Cumple_Antiguedad/Cotizacion_Enviada/Ultima_Cotizacion` a la capa legacy mientras siga como fallback; cambiar precondiciones para que precio con Moto+Plan_Credito+Plan_Enganche pregunte antiguedad o ejecute quote.resolve, nunca documentos; hacer que errores de provider/fallback no emitan texto de intermitencia al cliente. Mantener sin hardcodes Dinamo en core y pasar `test_dinamo_live_state_mismatch_regression.py`.
```

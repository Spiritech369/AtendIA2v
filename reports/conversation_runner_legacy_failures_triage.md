# Conversation Runner Legacy Failures Triage

Fecha: 2026-06-05

Decision: `NOT_READY_PREFLIGHT_FAILED`

## Resultado de reproduccion

Comando solicitado:

```bash
uv run pytest tests/runner/test_conversation_runner.py -q -vv
```

Primer intento sin DB de test:

- Resultado: `27 failed, 1 passed`
- Error comun: `ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection`
- Causa: la suite intentaba abrir DB sin `ATENDIA_TEST_DATABASE_URL` y con Postgres de test apagado.

Se intento levantar DB de test:

```bash
docker compose -f docker-compose.test.yml up -d postgres-test
```

Resultado:

- `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`
- Docker Desktop / daemon no disponible.

Despues del fix de harness, `test_conversation_runner.py` queda marcado `integration_db`, por lo que el comando sin URL de test aborta antes de tocar otra DB:

- Resultado: `pytest.exit: integration_db tests require ATENDIA_TEST_DATABASE_URL`

## Failures funcionales previos

Los 7 failures funcionales previos fueron tomados del reporte existente `reports/runner_suite_failure_triage.*`, generado cuando la DB de test si estaba disponible. Todos ocurrian en tenants legacy sin `runtime_v2_enabled=true`.

| test | error exacto | stack relevante | afecta runtime_v2_enabled=true | afecta solo legacy no-v2 | fallback visible | handoff | outbox/send | Dinamo smoke | clasificacion | fix minimo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `test_runner_validator_blocks_unsafe_composer_output` | expected `trace.outbound_messages is None`, got `['Y para seguir, dime que modelo quieres revisar.']` | `tests/runner/test_conversation_runner.py:790` | no | si | si | si | si | si, por waiver | `MUST_FIX_BEFORE_SMOKE` | ejecutar `composer_validator`, bloquear outbound y crear handoff si `needs_handoff` |
| `test_runner_24h_handoff_creates_row_no_compose` | `TypeError: build_handoff_summary() got an unexpected keyword argument 'document_requirements'` | `atendia/runner/conversation_runner.py:6296` | no | si | no | si | no | no directo | `LEGACY_ONLY_BUT_BLOCKS_RUNNER_SUITE` | aceptar aliases `document_requirements` / `document_requirements_field` en helper |
| `test_runner_composer_failure_creates_handoff` | expected one `human_handoffs` row, got `0` | `tests/runner/test_conversation_runner.py:988` | no | si | si | si | si | si, por waiver | `MUST_FIX_BEFORE_SMOKE` | reactivar persistencia de handoff `composer_failed`, bloquear outbound y emitir `fallback=disabled` |
| `test_runner_prefers_agent_flow_mode_rules_over_pipeline_rules` | expected `agent_retention:keyword_in_text`, got `agent_retention:keyword_in_text:agent_directed_from_ask_clarification` | `tests/runner/test_conversation_runner.py:1384` | no | si | no | no | no | no directo | `LEGACY_EXPECTATION_NEEDS_UPDATE` | aceptar prefijo estable del router trigger |
| `test_pending_confirmation_si_assigns_tipo_credito` | expected `pending_confirmation is None`, got `is_nomina_tarjeta` | `tests/runner/test_conversation_runner.py:1478` | no | si | no | no | no | no directo | `PREEXISTING_LEGACY_FAILURE` | restaurar mapa legacy string para `is_nomina_tarjeta` |
| `test_pending_confirmation_no_to_negocio_sat_assigns_sin_comprobantes` | expected `pending_confirmation is None`, got `is_negocio_sat` | `tests/runner/test_conversation_runner.py:1523` | no | si | no | no | no | no directo | `PREEXISTING_LEGACY_FAILURE` | restaurar mapa legacy string para `is_negocio_sat` |
| `test_composer_pending_confirmation_set_persists` | expected `is_nomina_recibos`, got `None` | `tests/runner/test_conversation_runner.py:1606` | no | si | no | no | no | no directo | `PREEXISTING_LEGACY_FAILURE` | preservar `pending_confirmation_set` emitido por composer si el response contract lo limpia |

## Fixes aplicados

- `handoff_helper.build_handoff_summary(...)` acepta `document_requirements` y `document_requirements_field` como compatibilidad legacy.
- `confirmation_policy` vuelve a resolver claves legacy string:
  - `is_nomina_tarjeta`
  - `is_negocio_sat`
- `conversation_runner` vuelve a persistir handoff para `composer_failed`.
- `conversation_runner` bloquea outbound en falla de composer y emite `fallback=disabled`.
- `conversation_runner` ejecuta `validate_composer_output(...)` y, si falla, bloquea outbound, agrega error `composer_validator` y crea handoff.
- `test_conversation_runner.py` acepta el prefijo estable del router trigger enriquecido.
- `test_conversation_runner.py` queda marcado `integration_db` para evitar tocar DB no-test por accidente.

## Estado de verificacion

Verificado:

- `uv run python -m py_compile atendia/runner/conversation_runner.py atendia/runner/confirmation_policy.py atendia/runner/handoff_helper.py tests/runner/test_conversation_runner.py`
  - Resultado: passed.
- `uv run ruff check atendia/runner/confirmation_policy.py atendia/runner/handoff_helper.py`
  - Resultado: `All checks passed!`

No verificado por DB/Docker apagado:

- `uv run pytest tests/runner/test_conversation_runner.py -q -vv`
- `uv run pytest tests/runner/test_conversation_runner.py -q`

## Waiver

No se emite waiver de runner verde. Aunque los fixes estan aplicados, falta reejecutar la suite con Postgres test disponible.

## Side effects

- WhatsApp enviado: no.
- Outbox live: no.
- Config live aplicada: no.
- Smoke/canary activado: no.
- Actions/workflows reales habilitados: no.

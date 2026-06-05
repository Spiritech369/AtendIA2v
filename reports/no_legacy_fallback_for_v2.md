# No Legacy Fallback For Runtime V2

Fecha: 2026-06-05

Decision: `NO_LEGACY_FALLBACK_FOR_V2_PARTIAL`

## Estado

La politica `Runtime V2 or no-send` sigue intacta:

- si `runtime_v2_enabled=true`, legacy no compone visible copy;
- si `runtime_v2_enabled=true`, legacy no escribe outbox;
- si `runtime_v2_enabled=true`, legacy no envia WhatsApp;
- si V2 falla, queda `no_send`;
- si provider fallback ocurre, queda bloqueado para visible send;
- tenants sin V2 siguen usando legacy.

## Fixes aplicados en esta fase

- Se restauro handoff `composer_failed` en el runner legacy.
- Se bloqueo outbound en falla de composer.
- Se agrego ejecucion de `composer_validator` para bloquear composer output inseguro.
- Se restauro compatibilidad de `build_handoff_summary` con callers legacy.
- Se restauro compatibilidad de `pending_confirmation` legacy string.
- Se preserva `pending_confirmation_set` emitido por composer cuando el response contract lo limpia.
- `test_conversation_runner.py` quedo marcado `integration_db` para no tocar DB no-test por accidente.

## Validacion ejecutada

- `uv run python -m py_compile atendia/runner/conversation_runner.py atendia/runner/confirmation_policy.py atendia/runner/handoff_helper.py tests/runner/test_conversation_runner.py`
  - Resultado: passed.
- `uv run ruff check atendia/runner/confirmation_policy.py atendia/runner/handoff_helper.py`
  - Resultado: `All checks passed!`
- `uv run pytest tests/architecture/test_dinamo_live_state_mismatch_regression.py -q`
  - Resultado: `3 passed, 2 warnings`.
- `uv run pytest tests/agent_runtime/test_runtime_v2_send_path_for_dinamo_smoke.py -m "not integration_db" -q`
  - Resultado: `3 passed, 7 deselected, 2 warnings`.
- `uv run pytest tests/agent_runtime/test_dinamo_shadow_e2e.py -q`
  - Resultado: `4 passed, 1 warning`.
- `uv run pytest tests/agent_runtime -m "not integration_db" -q`
  - Resultado: `214 passed, 43 deselected, 2 warnings`.

## Validacion bloqueada

- `docker compose -f docker-compose.test.yml up -d postgres-test`
  - Resultado: bloqueado; Docker daemon no disponible.
- `uv run pytest tests/runner/test_conversation_runner.py -q`
  - Resultado sin URL: aborta con `integration_db tests require ATENDIA_TEST_DATABASE_URL`.
- `uv run pytest tests/runner/test_conversation_runner.py -q -vv`
  - No reejecutado con DB por Docker apagado.
- `uv run pytest tests/agent_runtime/test_runtime_v2_send_path_for_dinamo_smoke.py -q`
  - Requiere integration DB para los tests marcados; sin URL aborta de forma segura.

## Ruff

Ruff enfocado en source files chicos paso.

Ruff incluyendo `conversation_runner.py` y `test_conversation_runner.py` sigue fallando por deuda global preexistente del archivo legacy: import sorting, line length, variables `cid` no usadas y otros hallazgos no relacionados con esta fase. No se hizo cleanup global.

## Side effects

- WhatsApp enviado: no.
- Outbox live escrito: no.
- Config live aplicada: no.
- Smoke/canary activado: no.
- Actions/workflows reales habilitados: no.

## Riesgo restante

No se puede promover a `NO_LEGACY_FALLBACK_FOR_V2_READY` hasta reejecutar la suite runner integration con Postgres test disponible y confirmar que los 7 failures quedaron verdes.

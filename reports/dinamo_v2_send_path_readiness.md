# Dinamo V2 Send Path Readiness

Fecha: 2026-06-05

Decision: `NOT_READY_PREFLIGHT_FAILED`

## Estado

El runtime v2 sigue preparado solo en modo no-send/prepared trace. No se activo trafico real.

## Checks que pasaron

- Arquitectura live-state mismatch: `3 passed, 2 warnings`.
- V2 send path no-DB: `3 passed, 7 deselected, 2 warnings`.
- Dinamo shadow E2E: `4 passed, 1 warning`.
- Agent runtime no-DB: `214 passed, 43 deselected, 2 warnings`.
- Compilacion de archivos modificados: passed.
- Ruff source enfocado: passed para `confirmation_policy.py` y `handoff_helper.py`.

## Blockers

1. `NOT_READY_PREFLIGHT_FAILED`
   - Docker daemon no disponible.
   - No se pudo reejecutar `tests/runner/test_conversation_runner.py` con Postgres test.
2. `NOT_READY_CONTRACT_NOT_PERSISTED`
   - Fixture Dinamo safe existe, pero persistencia DB no se pudo verificar.
3. `NOT_READY_MISSING_APPROVED_CONTACT`
   - No hay `contact_id` aprobado actual verificado.
   - Reportes historicos mencionan `+528212889421`, pero no se toma como aprobacion activa sin confirmacion/DB.

## No legacy fallback

Decision relacionada: `NO_LEGACY_FALLBACK_FOR_V2_PARTIAL`.

La politica esta implementada y las pruebas no-DB pasan, pero falta revalidar runner integration DB para cerrar READY.

## Traffic and config

- WhatsApp enviado: false.
- Outbox live escrito: false.
- Config live aplicada: false.
- Single-contact smoke activado: false.
- Canary activado: false.
- Actions reales habilitadas: false.
- Workflow side effects habilitados: false.

## Que falta para single-contact smoke

1. Encender Docker/Postgres test.
2. Ejecutar runner suite con:
   `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/runner/test_conversation_runner.py -q -vv`
3. Confirmar contrato Dinamo persistido o aplicar paquete aprobado con flags seguros.
4. Proveer exactamente un contacto aprobado vigente.
5. Reejecutar preflight completo.
6. Preparar rollback packet y pedir aprobacion humana explicita antes de activar cualquier smoke.

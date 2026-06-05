# AgentRuntime v2 E2E Safety Suite

Fecha: 2026-05-31

## Objetivo

La suite `core/tests/e2e/test_agent_runtime_v2_multitenant_safety.py` valida el camino integrado de AgentRuntime v2 con dos tenants paralelos. Su foco no es calidad conversacional, sino seguridad operacional:

- aislamiento multi-tenant;
- rollout policy por tenant/agente;
- preview/send sin cruce de datos;
- acciones reales y dry-run;
- workflow events reales y simulados;
- shadow mode sin side effects;
- trazas y logs con `tenant_id` correcto.

## Fixtures

Cada test crea dos tenants efimeros:

- tenant A y tenant B;
- un usuario `tenant_admin` por tenant;
- un agente activo por tenant;
- una `KnowledgeSource`, `KnowledgeItem` y `KnowledgeChunk` con marcador unico por tenant;
- un contact field distinto por tenant;
- un pipeline con stages `new` y `qualified`;
- una conversacion real por tenant;
- un mensaje inbound por tenant;
- un workflow controlado por tenant para `agent_confidence_low`.

Los datos se borran por cascada eliminando el tenant al final de cada test. No usa WhatsApp real, APIs externas ni provider LLM real.

## Casos Cubiertos

- Preview de tenant A solo recupera citations de knowledge A.
- Preview de tenant B solo recupera citations de knowledge B.
- Un agente no puede proponer acciones no habilitadas.
- `update_contact_field` de A no escribe memoria de B.
- `move_lifecycle` de A no mueve pipeline de B.
- Send queda bloqueado si la policy tenant-scoped no lo permite.
- Send permitido crea outbox solo para tenant A.
- Actions en dry-run registran log, pero no modifican tags/datos.
- Workflow events en dry-run no crean executions.
- Workflow events reales requieren flag global y policy de tenant.
- Shadow mode no escribe outbox, no ejecuta acciones y es idempotente por mensaje inbound.
- `ActionExecutionLog`, lifecycle history, citations y turn traces quedan asociados al tenant correcto.

## Migration Check

La suite incluye un smoke check de tablas criticas:

- `agent_readiness_eval_results`;
- `action_execution_logs`;
- `lifecycle_stage_history`.

No ejecuta `alembic downgrade`: el proyecto no mantiene downgrade como contrato operativo consistente para todas las migraciones actuales. Para CI limpia, correr antes desde `core/`:

```bash
uv run python -m alembic upgrade head
```

Luego ejecutar:

```bash
uv run python -m pytest core/tests/e2e/test_agent_runtime_v2_multitenant_safety.py
```

## Reglas de Seguridad Validadas

Los flags globales funcionan como upper-bound. Aunque tenant A tenga `send_enabled=true`, el test cambia `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED` para comprobar que send solo funciona cuando ambos niveles lo permiten.

Las acciones siguen pasando por `PostTurnActionExecutor`; el test cubre que `dry_run=true` no mute estado. Para ejecucion real controlada se prueban `update_contact_field` y `move_lifecycle` con evidencia/reason y se verifica que solo impacten al tenant propietario.

Los workflow events se prueban en modo simulado y real. En modo simulado se devuelven en debug, pero no crean `workflow_executions`. En modo real se exige flag global y policy tenant.

Shadow se ejecuta con `AgentRuntimeShadowService` sobre una conversacion real, pero no envia, no actualiza memoria, no mueve lifecycle, no ejecuta actions y no emite workflow events reales. La idempotencia se verifica con el mismo `inbound_message_id`.

## Gaps

- No valida canal WhatsApp ni ventanas/template reales.
- No usa provider LLM real; usa providers deterministas para hacer la suite estable.
- No cubre concurrencia de shadow con multiples workers.
- No cubre blueprints completos por industria; la suite es generalista y vertical-agnostic.
- No ejecuta `alembic downgrade`.

## Criterio de Produccion

Antes de permitir auto-send productivo, esta suite debe pasar junto con:

- tests focales de rollout policy;
- tests de readiness gate;
- tests de conversation preview/send;
- tests de action layer;
- tests de workflow events;
- tests de shadow service.

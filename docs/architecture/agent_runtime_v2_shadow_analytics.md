# AgentRuntime v2 Shadow Analytics

## Objetivo

`GET /api/v1/agent-runtime-v2/shadow-report` agrega trazas tenant-scoped de
shadow mode para comparar la salida legacy disponible contra `TurnOutput` de
AgentRuntime v2 antes de habilitar auto-send.

El reporte es read-only: no ejecuta actions, no emite workflow events, no toca
WhatsApp, no escribe outbox y no modifica traces historicos.

## Fuente de datos

El servicio `atendia.agent_runtime.shadow_analytics.AgentRuntimeV2ShadowAnalyticsService`
lee `turn_traces` con:

- `router_trigger = agent_runtime_v2_shadow`
- `router_trigger = agent_runtime_v2_shadow_auto`

El servicio tambien cruza `conversations` solo para aplicar filtro `channel`.
El scope obligatorio es `TurnTrace.tenant_id == tenant_id`, resuelto desde la
sesion actual por `current_tenant_id`.

Campos consumidos:

- `composer_output.final_message`
- `composer_output.confidence`
- `composer_output.needs_human`
- `composer_output.risk_flags`
- `composer_output.knowledge_citations`
- `composer_output.actions`
- `composer_output.field_updates`
- `composer_output.lifecycle_update`
- `state_after.comparison.legacy_final_message`
- `state_after.comparison.policy_issues`
- `kb_evidence.citations`
- `rules_evaluated`
- `errors`

## Endpoint

`GET /api/v1/agent-runtime-v2/shadow-report`

Permisos:

- `tenant_admin`
- `superadmin`

Filtros:

- `date_from`
- `date_to`
- `agent_id`
- `conversation_id`
- `channel`
- `min_confidence`
- `include_examples`
- `limit`

## Respuesta

```json
{
  "summary": {
    "shadow_turns": 12,
    "avg_confidence": 0.82,
    "needs_human_count": 2,
    "policy_blocked_count": 1,
    "knowledge_gap_count": 3,
    "actions_proposed_count": 4,
    "field_updates_proposed_count": 5,
    "lifecycle_updates_proposed_count": 1,
    "errors_count": 1
  },
  "legacy_vs_v2": {
    "legacy_message_available_count": 10,
    "v2_message_available_count": 11,
    "same_or_similar_count": 7,
    "v2_empty_count": 1,
    "legacy_empty_count": 2,
    "needs_human_when_legacy_answered_count": 1
  },
  "top_risk_flags": [],
  "top_policy_issues": [],
  "top_knowledge_sources": [],
  "pilot_inputs": {
    "shadow_sample_size": 12,
    "avg_shadow_confidence": 0.82,
    "policy_block_rate": 0.0833,
    "needs_human_rate": 0.1667
  },
  "examples": []
}
```

`pilot_inputs` prepara el puente con limited manual-send pilot:

- `shadow_sample_size`
- `avg_shadow_confidence`
- `policy_block_rate`
- `needs_human_rate`

## Comparacion deterministica

No hay LLM judge en esta version. Cada ejemplo incluye heuristicas booleanas:

- `both_have_message`
- `v2_empty`
- `legacy_empty`
- `v2_needs_human`
- `v2_low_confidence`
- `v2_has_citations`
- `v2_proposed_action`
- `v2_proposed_field_update`
- `v2_proposed_lifecycle_update`
- `length_delta_extreme`
- `possible_generic_non_answer`

`same_or_similar_count` usa comparacion exacta normalizada o similitud de texto
deterministica con umbral alto. Esto sirve para triage operacional, no para
calidad semantica final.

## Gaps conocidos

- No hay judge semantico ni scoring por vertical.
- Si el trace no trae `state_after.comparison.legacy_final_message`, legacy se
  reporta como no disponible.
- La deteccion de no-respuesta es conservadora y basada en texto generico.
- No se calcula aun win/loss por categoria de negocio.

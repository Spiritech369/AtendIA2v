# Dinamo OpenAI Precheck - 2026-06-02

## Identity

- tenant_email: `dinamomotosnl@gmail.com`
- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- provider/model: `openai` / `gpt-4o-mini`
- OPENAI_API_KEY present: `true`
- critical_passed: `true`

## Rollout Config

```json
{
  "metadata": {
    "owner": "dinamomotosnl@gmail.com",
    "setup": "dinamo_fresh_tenant_v1",
    "live_ready": false
  },
  "rollout_mode": "preview_only",
  "send_enabled": false,
  "min_eval_score": 0.9,
  "outbox_enabled": false,
  "actions_enabled": false,
  "preview_enabled": true,
  "ready_for_shadow": false,
  "auto_send_enabled": false,
  "runtime_v2_enabled": true,
  "manual_send_enabled": false,
  "shadow_mode_enabled": false,
  "last_readiness_score": 0.0,
  "max_actions_per_turn": 2,
  "ready_for_manual_send": false,
  "model_provider_enabled": true,
  "ready_for_live_preview": false,
  "last_readiness_suite_id": "agent_runtime_v2_dinamo_fresh_openai_readiness",
  "workflow_events_enabled": false,
  "last_readiness_updated_at": "2026-06-02T10:35:31.627325+00:00",
  "required_eval_suite_passed": false
}
```

## Checks

- tenant_verified: `pass`
- tenant_is_real: `pass`
- agent_verified: `pass`
- rollout_flags_safe: `pass`
- openai_key_present: `pass`
- provider_openai: `pass`
- model_present: `pass`
- factual_sources_only: `pass`
- non_factual_sources_disabled: `pass`
- prompt_and_flow_present: `pass`

## Knowledge Sources

| source | id | content_type | status | factual_enabled |
| --- | --- | --- | --- | --- |
| `catalogo_dinamo` | `9ce2ddb6-0277-53cb-9dcc-f7a62facbb76` | `catalog` | `active` | `True` |
| `faq_dinamo` | `ce1f452e-88a8-5f87-b2f2-99ce8171b507` | `faq` | `active` | `True` |
| `flujo_dinamo_orden_caos` | `1873a9da-45a0-5957-9b96-afdb509b14ac` | `general` | `active` | `False` |
| `prompt_agente_dinamo` | `51892528-bb70-5a50-a5d4-e3203948fe0d` | `general` | `active` | `False` |
| `requisitos_dinamo` | `5a02c31f-392c-58e0-acf1-9abdd275f71c` | `document_rules` | `active` | `True` |

## Factual Source Decision

- factual_sources_enabled: `['catalogo_dinamo', 'faq_dinamo', 'requisitos_dinamo']`
- non_factual_sources_enabled: `[]`
- prompt_agente_dinamo: `configuration/instructions only`
- flujo_dinamo_orden_caos: `eval/simulation only`

## Decision

OpenAI provider run allowed.

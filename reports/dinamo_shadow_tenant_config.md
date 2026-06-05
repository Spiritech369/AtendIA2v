# Dinamo Shadow Tenant Config

Decision: `DINAMO_SHADOW_READY`

Generated at: `2026-06-03T22:24:52.1570446-06:00`

## Runtime Scope

This is a shadow/preview/dry-run proposal only. It was not applied to a live database and it does not enable sends, actions, workflow side effects, canary traffic, or single-contact smoke.

```json
{
  "contract_version": "1.0",
  "tenant_id": "6ad78236-1fc9-467a-858d-90d248d57ee5",
  "agent_id": "c169deec-226d-55b7-bd07-270f339e75a6",
  "domain": "vehicle_credit_sales",
  "locale": "es-MX",
  "timezone": "America/Mexico_City",
  "runtime_mode": "v2_shadow_until_evaluated",
  "live_send_enabled": false,
  "actions_enabled": false,
  "workflow_side_effects_enabled": false
}
```

## Fixture

Created fixture:

- `core/tests/agent_runtime/fixtures/tenant_domain_contracts/dinamo_motos_nl_shadow.json`

It includes tenant metadata for Dinamo Motos NL, Francisco de Dinamo NL, business owner Francisco Esparza, rollback owner Felipe Balderas, and all runtime flags forced to shadow/dry-run.

## Field Map

- `product_selection` / Moto seleccionada
- `product_catalog_id` / ID catalogo
- `purchase_type` / Tipo de compra
- `employment_seniority` / Antiguedad
- `eligibility_seniority` / Cumple antiguedad
- `plan_selection` / Plan de credito
- `down_payment_percent` / Enganche %
- `quote_snapshot_id` / Cotizacion validada
- `payment_amount` / Pago
- `cash_price` / Precio contado
- `requirements_checklist` / Checklist documentos
- `requirements_missing` / Documentos faltantes
- `requirements_complete` / Papeleria completa
- `bureau_mentioned` / Buro mencionado
- `bureau_status` / Estado buro
- `human_handoff_needed` / Requiere humano
- `handoff_reason` / Motivo handoff
- `followup_status` / Seguimiento

## Tools

- `catalog.search`
- `credit_plan.resolve`
- `quote.resolve`
- `requirements.lookup`
- `faq.lookup`
- `document.check`
- `handoff.create`
- `followup.schedule`

All tool results used in tests are tenant-scoped fake dry-run results.

## Pipeline

- `nuevo`
- `primer_contacto`
- `moto_identificada`
- `plan_identificado`
- `cotizado`
- `papeleria_solicitada`
- `papeleria_recibida`
- `papeleria_completa`
- `en_revision_humana`
- `cerrado_ganado`
- `cerrado_perdido`

## Business Events

- `lead_started`
- `intent_identified`
- `selection_identified`
- `plan_identified`
- `offer_quoted`
- `requirements_requested`
- `document_received`
- `requirements_partial`
- `requirements_complete`
- `human_handoff_requested`
- `followup_scheduled`
- `policy_blocked`
- `conversation_closed`

## Guards

- `mandatory_tool_guard`
- `quote_snapshot_guard`
- `no_cash_quote_for_credit_guard`
- `requirements_plan_guard`
- `attachment_evidence_guard`
- `doc_complete_guard`
- `no_approval_guard`
- `bureau_no_auto_reject_guard`
- `workflow_idempotency_guard`
- `provider_fallback_guard`
- `repetition_progress_guard`

## Notes

The config is persisted only as a test fixture and report proposal. No Dinamo config was applied live.

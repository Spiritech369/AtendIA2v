# Dinamo Shadow E2E Report

Decision: `DINAMO_SHADOW_READY`

Generated at: `2026-06-03T22:24:52.1570446-06:00`

## Scenario

Six deterministic turns were simulated in `tests/agent_runtime/test_dinamo_shadow_e2e.py`. The test uses real agent_runtime_v2 contracts and fake tenant-scoped tool results. No DB, WhatsApp, live send, actions, workflows, canary, or single-contact smoke were activated.

## Turn Results

1. Customer asks for R4, bureau, income outside payroll, and location.
   - Tools: `catalog.search`, `credit_plan.resolve`, `faq.lookup`
   - State accepted: `product_selection`, `product_catalog_id`, `purchase_type`, `plan_selection`, `down_payment_percent`, `bureau_mentioned`
   - Pipeline: `plan_identificado`
   - No `quote.resolve`; no quote emitted because seniority was missing
   - Events: `lead_started`, `intent_identified`, `selection_identified`, `plan_identified`

2. Customer says they have 8 months seniority.
   - Tools: `credit_plan.resolve`, `quote.resolve`
   - State accepted: `employment_seniority`, `eligibility_seniority`, `quote_snapshot_id`, `payment_amount`, `cash_price`
   - Pipeline: `cotizado`
   - Events: `offer_quoted`

3. Customer asks for requirements and says they have no payroll receipts.
   - Tools: `requirements.lookup`
   - State accepted: `requirements_checklist`
   - Pipeline: `papeleria_solicitada`
   - Events: `requirements_requested`

4. Customer says they will send INE later.
   - Tools: none
   - State accepted: none
   - Pipeline: unchanged
   - No `document.check`
   - No `document_received`

5. Customer sends INE attachment.
   - Tools: `requirements.lookup`, `document.check`
   - State accepted: `requirements_missing`, `requirements_complete=false`
   - Pipeline: `papeleria_recibida`
   - Events: `document_received`, `requirements_partial`

6. Customer sends proof of address attachment.
   - Tools: `requirements.lookup`, `document.check`, `handoff.create`
   - State accepted: `requirements_complete=true`, `human_handoff_needed`, `handoff_reason`
   - Pipeline: `en_revision_humana`
   - Events: `document_received`, `requirements_complete`, `human_handoff_requested`
   - No approval was promised

## Universal Trace

Every turn produced:

- `universal_turn_trace`
- `gpt_proposed`
- `atendia_validation`
- `mandatory_tool_decisions`
- `tool_results`
- `state_changes`
- `business_events`
- `guards`
- `lifecycle`
- `final_output`

## Dry-Run Business Events

All business events have `status=dry_run`. All workflow results have `status=dry-run`, `dry_run=true`, and `side_effects_allowed=false`.

## Frontend Fixture

Created:

- `frontend/src/features/turn-traces/__fixtures__/dinamoShadowUniversalTrace.ts`

The fixture exports six turns and the latest trace for `UniversalTracePanel` tests.

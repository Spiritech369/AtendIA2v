import type { UniversalTraceRecord } from "../lib/universalTrace";

const realReplayAudit = {
  safe_mode: false,
  tenant_domain_contract: {
    version: "1.0",
    domain: "vehicle_credit_sales",
    safe_mode: false,
    runtime_mode: "v2_shadow_until_evaluated",
  },
  visible_text_authority: "TurnOutput.final_message",
  tool_visible_text_allowed: false,
  raw_trace_preserved: true,
};

export const dinamoShadowRealReplayTrace: UniversalTraceRecord = {
  trace_version: "1.0",
  turn_id: "real-replay-turn-quote-1",
  tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
  agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
  conversation_id: "real_16a192a09810",
  contact_id: "anon_contact_real_replay",
  domain: "vehicle_credit_sales",
  input: {
    inbound_text: "cliente solicita cotizacion de moto modelo anonimo",
    anonymized: true,
    raw_text_exported: false,
  },
  gpt_understanding: {
    customer_goal: "vehicle_credit_sales",
    next_best_action: "quote_with_shadow_snapshot",
    response_plan: "Use tenant tools and keep the customer-facing copy in final_output.",
    confidence: 0.92,
  },
  gpt_proposed: {
    state_changes: [
      { target: "contact_field", key: "product_selection", value: "modelo_anonimo" },
      { target: "contact_field", key: "quote_snapshot_id", value: "shadow_quote_snapshot" },
      { target: "contact_field", key: "cash_price", value: "blocked_user_visible_price" },
    ],
    required_tools: [
      { name: "catalog.search", required: true },
      { name: "credit_plan.resolve", required: true },
      { name: "quote.resolve", required: true },
    ],
    visible_text_allowed: false,
  },
  mandatory_tool_decisions: [
    { tool_id: "catalog.search", status: "executed", required: true, blocking: false },
    { tool_id: "credit_plan.resolve", status: "executed", required: true, blocking: false },
    { tool_id: "quote.resolve", status: "executed", required: true, blocking: false },
  ],
  tool_results: [
    {
      tool_id: "catalog.search",
      status: "succeeded",
      tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
      safe_inputs: { query: "modelo_anonimo" },
      structured_output: { matched: true, product_ref: "catalog_shadow_match" },
      used_for: ["state_write_validation"],
      visible_text_allowed: false,
    },
    {
      tool_id: "credit_plan.resolve",
      status: "succeeded",
      tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
      safe_inputs: { plan_hint: "shadow_default" },
      structured_output: { plan_code: "shadow_plan", side_effects: false },
      used_for: ["state_write_validation"],
      visible_text_allowed: false,
    },
    {
      tool_id: "quote.resolve",
      status: "succeeded",
      tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
      safe_inputs: { product_ref: "catalog_shadow_match" },
      structured_output: { snapshot_id: "shadow_quote_snapshot", dry_run: true },
      used_for: ["quote_validation"],
      visible_text_allowed: false,
    },
  ],
  atendia_validation: {
    mandatory_tool_decisions: [
      { tool_id: "catalog.search", status: "executed", required: true, blocking: false },
      { tool_id: "credit_plan.resolve", status: "executed", required: true, blocking: false },
      { tool_id: "quote.resolve", status: "executed", required: true, blocking: false },
    ],
    state_writer: {
      accepted: [
        { field: "product_selection", decision: "accepted", source: "catalog.search" },
        { field: "product_catalog_id", decision: "accepted", source: "catalog.search" },
        { field: "quote_snapshot_id", decision: "accepted", source: "quote.resolve" },
      ],
      blocked: [
        {
          field: "cash_price",
          decision: "blocked",
          reason: "visible_price_requires_quote_snapshot_copy_policy",
          source: "user_message",
        },
      ],
      needs_review: [],
      summary: { accepted_count: 3, blocked_count: 1, needs_review_count: 0 },
    },
    guards: [
      {
        guard_id: "quote_snapshot_guard",
        result: "passed",
        reason: "quote.resolve_executed",
      },
    ],
    safe_mode: false,
  },
  state_changes: {
    field_updates: [
      { field_key: "product_selection", value: "modelo_anonimo" },
      { field_key: "product_catalog_id", value: "catalog_shadow_match" },
      { field_key: "quote_snapshot_id", value: "shadow_quote_snapshot" },
    ],
    accepted: [
      { field: "product_selection", decision: "accepted", source: "catalog.search" },
      { field: "product_catalog_id", decision: "accepted", source: "catalog.search" },
      { field: "quote_snapshot_id", decision: "accepted", source: "quote.resolve" },
    ],
    blocked: [
      {
        field: "cash_price",
        decision: "blocked",
        reason: "visible_price_requires_quote_snapshot_copy_policy",
      },
    ],
    needs_review: [],
    summary: { accepted_count: 3, blocked_count: 1, needs_review_count: 0 },
  },
  lifecycle: {
    stage_before: "moto_identificada",
    stage_proposed: "cotizado",
    stage_after: "cotizado",
    validated_update: { target_stage: "cotizado" },
  },
  business_events: [
    { event_type: "offer_quoted", status: "dry_run", dry_run: true },
    { event_type: "intent_identified", status: "dry_run", dry_run: true },
  ],
  workflow_results: [
    {
      event_type: "offer_quoted",
      status: "dry-run",
      dry_run: true,
      side_effects_allowed: false,
    },
  ],
  guards: [
    { guard_id: "quote_snapshot_guard", result: "passed", reason: "quote.resolve_executed" },
  ],
  provider: {
    provider: "deterministic_shadow_replay",
    reliability: { fallback_used: false },
  },
  final_output: {
    final_message:
      "Real replay shadow: cotizacion validada por quote.resolve en dry-run. No se envia WhatsApp ni se aplica config live.",
    source: "TurnOutput.final_message",
    visible_to_customer: true,
    confidence: 0.92,
    risk_flags: [],
  },
  audit: realReplayAudit,
};

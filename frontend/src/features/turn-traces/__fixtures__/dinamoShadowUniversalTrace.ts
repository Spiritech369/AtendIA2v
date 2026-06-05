import type { UniversalTraceRecord } from "../lib/universalTrace";

const baseAudit = {
  safe_mode: false,
  tenant_domain_contract: {
    version: "1.0",
    domain: "vehicle_credit_sales",
    safe_mode: false,
  },
  visible_text_authority: "TurnOutput.final_message",
  tool_visible_text_allowed: false,
  raw_trace_preserved: true,
};

export const dinamoShadowUniversalTraceTurns = [
  {
    trace_version: "1.0",
    turn_id: "dinamo-shadow-turn-1",
    tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
    agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
    conversation_id: "dinamo-shadow-conversation-1",
    contact_id: "dinamo-shadow-contact-1",
    domain: "vehicle_credit_sales",
    input: {
      text: "Hola, me interesa la R4, traigo buro y me pagan por fuera. Donde estan?",
    },
    gpt_understanding: {
      customer_goal: "vehicle_credit_sales",
      next_best_action: "ask_seniority_before_quote",
    },
    gpt_proposed: {
      state_changes: [
        { target: "contact_field", key: "product_selection", value: "R4 250 CC" },
        { target: "contact_field", key: "plan_selection", value: "Sin Comprobantes" },
        { target: "contact_field", key: "bureau_mentioned", value: true },
      ],
    },
    mandatory_tool_decisions: [
      { tool_id: "catalog.search", status: "executed", blocking: false },
      { tool_id: "credit_plan.resolve", status: "executed", blocking: false },
      { tool_id: "faq.lookup", status: "executed", blocking: false },
    ],
    tool_results: [
      { tool_name: "catalog.search", status: "succeeded" },
      { tool_name: "credit_plan.resolve", status: "succeeded" },
      { tool_name: "faq.lookup", status: "succeeded" },
    ],
    atendia_validation: {
      mandatory_tool_decisions: [
        { tool_id: "catalog.search", status: "executed", blocking: false },
        { tool_id: "credit_plan.resolve", status: "executed", blocking: false },
        { tool_id: "faq.lookup", status: "executed", blocking: false },
      ],
      state_writer: {
        accepted: [
          { field: "product_selection", decision: "accepted", source: "user_message" },
          { field: "plan_selection", decision: "accepted", source: "user_message" },
          { field: "bureau_mentioned", decision: "accepted", source: "user_message" },
        ],
        blocked: [],
        needs_review: [],
        summary: { accepted_count: 6, blocked_count: 0, needs_review_count: 0 },
      },
      guards: [],
      safe_mode: false,
    },
    state_changes: {
      field_updates: [
        { field_key: "product_selection", value: "R4 250 CC" },
        { field_key: "plan_selection", value: "Sin Comprobantes" },
        { field_key: "bureau_mentioned", value: true },
      ],
      accepted: [
        { field: "product_selection", decision: "accepted" },
        { field: "plan_selection", decision: "accepted" },
        { field: "bureau_mentioned", decision: "accepted" },
      ],
      blocked: [],
      needs_review: [],
    },
    lifecycle: { target_stage: "plan_identificado" },
    business_events: [
      { event_type: "lead_started", status: "dry_run", reason: "first_turn_or_new_conversation" },
      { event_type: "selection_identified", status: "dry_run" },
      { event_type: "plan_identified", status: "dry_run" },
    ],
    workflow_results: [
      { event_type: "selection_identified", status: "dry-run", dry_run: true },
      { event_type: "plan_identified", status: "dry-run", dry_run: true },
    ],
    guards: [],
    provider: { name: "dinamo_shadow_e2e" },
    final_output: {
      final_message:
        "Tengo ubicada la R4 y el plan Sin Comprobantes en shadow. Antes de cotizar necesito saber cuantos meses tienes de antiguedad.",
      source: "TurnOutput.final_message",
      visible_to_customer: true,
    },
    audit: baseAudit,
  },
  {
    trace_version: "1.0",
    turn_id: "dinamo-shadow-turn-2",
    tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
    agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
    conversation_id: "dinamo-shadow-conversation-1",
    contact_id: "dinamo-shadow-contact-1",
    domain: "vehicle_credit_sales",
    input: { text: "Tengo 8 meses" },
    gpt_understanding: {
      customer_goal: "vehicle_credit_sales",
      next_best_action: "quote_with_snapshot",
    },
    gpt_proposed: {
      state_changes: [{ target: "contact_field", key: "employment_seniority", value: 8 }],
    },
    mandatory_tool_decisions: [
      { tool_id: "credit_plan.resolve", status: "executed", blocking: false },
      { tool_id: "quote.resolve", status: "executed", blocking: false },
    ],
    tool_results: [
      { tool_name: "credit_plan.resolve", status: "succeeded" },
      { tool_name: "quote.resolve", status: "succeeded" },
    ],
    atendia_validation: {
      state_writer: {
        accepted: [
          { field: "employment_seniority", decision: "accepted" },
          { field: "quote_snapshot_id", decision: "accepted", source: "quote.resolve" },
        ],
        blocked: [],
        needs_review: [],
        summary: { accepted_count: 5, blocked_count: 0, needs_review_count: 0 },
      },
      guards: [],
      safe_mode: false,
    },
    state_changes: {
      field_updates: [
        { field_key: "employment_seniority", value: 8 },
        { field_key: "eligibility_seniority", value: true },
        { field_key: "quote_snapshot_id", value: "quote-r4-sin-comprobantes-shadow" },
        { field_key: "payment_amount", value: 1450 },
      ],
      accepted: [
        { field: "employment_seniority", decision: "accepted" },
        { field: "quote_snapshot_id", decision: "accepted" },
      ],
      blocked: [],
      needs_review: [],
    },
    lifecycle: { target_stage: "cotizado" },
    business_events: [{ event_type: "offer_quoted", status: "dry_run" }],
    workflow_results: [{ event_type: "offer_quoted", status: "dry-run", dry_run: true }],
    guards: [],
    provider: { name: "dinamo_shadow_e2e" },
    final_output: {
      final_message:
        "Con 8 meses ya puedo usar la cotizacion validada: pago shadow $1,450 con enganche 20%.",
      source: "TurnOutput.final_message",
      visible_to_customer: true,
    },
    audit: baseAudit,
  },
  {
    trace_version: "1.0",
    turn_id: "dinamo-shadow-turn-3",
    tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
    agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
    conversation_id: "dinamo-shadow-conversation-1",
    contact_id: "dinamo-shadow-contact-1",
    domain: "vehicle_credit_sales",
    input: { text: "Si, pasame que ocupo. No tengo comprobantes." },
    gpt_understanding: {
      customer_goal: "vehicle_credit_sales",
      next_best_action: "request_requirements",
    },
    gpt_proposed: { state_changes: [] },
    mandatory_tool_decisions: [
      { tool_id: "requirements.lookup", status: "executed", blocking: false },
    ],
    tool_results: [{ tool_name: "requirements.lookup", status: "succeeded" }],
    atendia_validation: {
      state_writer: {
        accepted: [{ field: "requirements_checklist", decision: "accepted" }],
        blocked: [],
        needs_review: [],
        summary: { accepted_count: 1, blocked_count: 0, needs_review_count: 0 },
      },
      guards: [],
      safe_mode: false,
    },
    state_changes: {
      field_updates: [{ field_key: "requirements_checklist", value: ["ine", "domicilio"] }],
      accepted: [{ field: "requirements_checklist", decision: "accepted" }],
      blocked: [],
      needs_review: [],
    },
    lifecycle: { target_stage: "papeleria_solicitada" },
    business_events: [{ event_type: "requirements_requested", status: "dry_run" }],
    workflow_results: [{ event_type: "requirements_requested", status: "dry-run", dry_run: true }],
    guards: [],
    provider: { name: "dinamo_shadow_e2e" },
    final_output: {
      final_message:
        "Para el plan Sin Comprobantes, en shadow la lista validada pide INE vigente y comprobante de domicilio.",
      source: "TurnOutput.final_message",
      visible_to_customer: true,
    },
    audit: baseAudit,
  },
  {
    trace_version: "1.0",
    turn_id: "dinamo-shadow-turn-4",
    tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
    agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
    conversation_id: "dinamo-shadow-conversation-1",
    contact_id: "dinamo-shadow-contact-1",
    domain: "vehicle_credit_sales",
    input: { text: "Te mando la INE al rato" },
    gpt_understanding: {
      customer_goal: "vehicle_credit_sales",
      next_best_action: "wait_for_attachment",
    },
    gpt_proposed: { state_changes: [] },
    mandatory_tool_decisions: [],
    tool_results: [],
    atendia_validation: {
      state_writer: {
        accepted: [],
        blocked: [],
        needs_review: [],
        summary: { accepted_count: 0, blocked_count: 0, needs_review_count: 0 },
      },
      guards: [],
      safe_mode: false,
    },
    state_changes: { field_updates: [], accepted: [], blocked: [], needs_review: [] },
    lifecycle: {},
    business_events: [{ event_type: "intent_identified", status: "dry_run" }],
    workflow_results: [{ event_type: "intent_identified", status: "dry-run", dry_run: true }],
    guards: [],
    provider: { name: "dinamo_shadow_e2e" },
    final_output: {
      final_message: "Claro, cuando lo tengas lo revisamos en shadow.",
      source: "TurnOutput.final_message",
      visible_to_customer: true,
    },
    audit: baseAudit,
  },
  {
    trace_version: "1.0",
    turn_id: "dinamo-shadow-turn-5",
    tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
    agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
    conversation_id: "dinamo-shadow-conversation-1",
    contact_id: "dinamo-shadow-contact-1",
    domain: "vehicle_credit_sales",
    input: { text: "[Adjunto INE]" },
    gpt_understanding: {
      customer_goal: "vehicle_credit_sales",
      next_best_action: "check_document_partial",
    },
    gpt_proposed: { state_changes: [] },
    mandatory_tool_decisions: [
      { tool_id: "document.check", status: "executed", blocking: false },
      { tool_id: "requirements.lookup", status: "executed", blocking: false },
    ],
    tool_results: [
      { tool_name: "requirements.lookup", status: "succeeded" },
      { tool_name: "document.check", status: "succeeded" },
    ],
    atendia_validation: {
      state_writer: {
        accepted: [
          { field: "requirements_missing", decision: "accepted" },
          { field: "requirements_complete", decision: "accepted" },
        ],
        blocked: [],
        needs_review: [],
        summary: { accepted_count: 3, blocked_count: 0, needs_review_count: 0 },
      },
      guards: [],
      safe_mode: false,
    },
    state_changes: {
      field_updates: [
        { field_key: "requirements_missing", value: ["comprobante_domicilio"] },
        { field_key: "requirements_complete", value: false },
      ],
      accepted: [
        { field: "requirements_missing", decision: "accepted" },
        { field: "requirements_complete", decision: "accepted" },
      ],
      blocked: [],
      needs_review: [],
    },
    lifecycle: { target_stage: "papeleria_recibida" },
    business_events: [
      { event_type: "document_received", status: "dry_run" },
      { event_type: "requirements_partial", status: "dry_run" },
    ],
    workflow_results: [
      { event_type: "document_received", status: "dry-run", dry_run: true },
      { event_type: "requirements_partial", status: "dry-run", dry_run: true },
    ],
    guards: [],
    provider: { name: "dinamo_shadow_e2e" },
    final_output: {
      final_message:
        "Recibi un archivo y document.check lo marco parcial; falta completar comprobante de domicilio.",
      source: "TurnOutput.final_message",
      visible_to_customer: true,
    },
    audit: baseAudit,
  },
  {
    trace_version: "1.0",
    turn_id: "dinamo-shadow-turn-6",
    tenant_id: "6ad78236-1fc9-467a-858d-90d248d57ee5",
    agent_id: "c169deec-226d-55b7-bd07-270f339e75a6",
    conversation_id: "dinamo-shadow-conversation-1",
    contact_id: "dinamo-shadow-contact-1",
    domain: "vehicle_credit_sales",
    input: { text: "[Adjunto comprobante domicilio]" },
    gpt_understanding: {
      customer_goal: "vehicle_credit_sales",
      next_best_action: "handoff_for_human_review",
    },
    gpt_proposed: { state_changes: [] },
    mandatory_tool_decisions: [
      { tool_id: "requirements.lookup", status: "executed", blocking: false },
      { tool_id: "document.check", status: "executed", blocking: false },
      { tool_id: "handoff.create", status: "executed", blocking: false },
    ],
    tool_results: [
      { tool_name: "requirements.lookup", status: "succeeded" },
      { tool_name: "document.check", status: "succeeded" },
      { tool_name: "handoff.create", status: "succeeded" },
    ],
    atendia_validation: {
      state_writer: {
        accepted: [
          { field: "requirements_complete", decision: "accepted" },
          { field: "human_handoff_needed", decision: "accepted" },
          { field: "handoff_reason", decision: "accepted" },
        ],
        blocked: [],
        needs_review: [],
        summary: { accepted_count: 5, blocked_count: 0, needs_review_count: 0 },
      },
      guards: [],
      safe_mode: false,
    },
    state_changes: {
      field_updates: [
        { field_key: "requirements_complete", value: true },
        { field_key: "human_handoff_needed", value: true },
        { field_key: "handoff_reason", value: "requirements_complete_needs_human_review" },
      ],
      accepted: [
        { field: "requirements_complete", decision: "accepted" },
        { field: "human_handoff_needed", decision: "accepted" },
        { field: "handoff_reason", decision: "accepted" },
      ],
      blocked: [],
      needs_review: [],
    },
    lifecycle: { target_stage: "en_revision_humana" },
    business_events: [
      { event_type: "document_received", status: "dry_run" },
      { event_type: "requirements_complete", status: "dry_run" },
      { event_type: "human_handoff_requested", status: "dry_run" },
    ],
    workflow_results: [
      { event_type: "requirements_complete", status: "dry-run", dry_run: true },
      { event_type: "human_handoff_requested", status: "dry-run", dry_run: true },
    ],
    guards: [],
    provider: { name: "dinamo_shadow_e2e" },
    final_output: {
      final_message:
        "Ya quedo la papeleria completa para revision humana. Esto solo avanza a revision; aun no hay resolucion final.",
      source: "TurnOutput.final_message",
      visible_to_customer: true,
    },
    audit: baseAudit,
  },
] satisfies UniversalTraceRecord[];

export const dinamoShadowLatestUniversalTrace: UniversalTraceRecord =
  dinamoShadowUniversalTraceTurns[dinamoShadowUniversalTraceTurns.length - 1]!;

import { describe, expect, it } from "vitest";

import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { buildTurnStory } from "@/features/turn-traces/lib/turnStory";

const baseTrace: TurnTraceDetail = {
  id: "t1",
  conversation_id: "c1",
  turn_number: 1,
  inbound_message_id: "m1",
  inbound_preview: "¿Cuánto cuesta?",
  flow_mode: "SALES",
  nlu_model: "gpt-4o-mini",
  composer_model: "gpt-4o",
  total_cost_usd: "0.001",
  total_latency_ms: 1200,
  bot_paused: false,
  created_at: "2026-05-12T00:00:00Z",
  inbound_text: "¿Cuánto cuesta?",
  nlu_input: null,
  nlu_output: {
    intent: "ask_price",
    entities: {
      brand: { value: "Honda", confidence: 0.9, source_turn: 1 },
      model: { value: "Civic", confidence: 0.85, source_turn: 1 },
    },
    sentiment: "neutral",
    confidence: 0.92,
    ambiguities: [],
  },
  nlu_tokens_in: null,
  nlu_tokens_out: null,
  nlu_cost_usd: null,
  nlu_latency_ms: 300,
  composer_input: { action: "quote", action_payload: {} },
  composer_output: {
    messages: ["Hola, el modelo cuesta $325,000"],
    pending_confirmation_set: null,
  },
  composer_tokens_in: null,
  composer_tokens_out: null,
  composer_cost_usd: "0.0008",
  composer_latency_ms: 800,
  vision_cost_usd: null,
  vision_latency_ms: null,
  tool_cost_usd: null,
  state_before: { current_stage: "lead_warm" },
  state_after: { current_stage: "quote_sent" },
  stage_transition: "lead_warm → quote_sent",
  outbound_messages: [{ text: "Hola, el modelo cuesta $325,000" }],
  errors: null,
  tool_calls: [],
  router_trigger: null,
  raw_llm_response: null,
  agent_id: null,
  kb_evidence: null,
  rules_evaluated: null,
  composer_provider: null,
  inbound_text_cleaned: null,
};

describe("buildTurnStory", () => {
  it("emits inbound step from inbound_text", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps[0]).toMatchObject({
      kind: "inbound",
      text: "¿Cuánto cuesta?",
    });
  });

  it("emits nlu step with intent + confidence + entity count", () => {
    const steps = buildTurnStory(baseTrace);
    const nlu = steps.find((s) => s.kind === "nlu");
    expect(nlu).toMatchObject({
      kind: "nlu",
      intent: "ask_price",
      confidence: 0.92,
      entityCount: 2,
    });
  });

  it("emits mode step from flow_mode with a derived rationale", () => {
    const steps = buildTurnStory(baseTrace);
    const mode = steps.find((s) => s.kind === "mode");
    expect(mode).toMatchObject({ kind: "mode", mode: "SALES" });
    // rationale is best-effort; when an action exists we surface it.
    expect((mode as { rationale: string | null }).rationale).toContain("quote");
  });

  it("emits composer step with messages and latency/cost metadata", () => {
    const steps = buildTurnStory(baseTrace);
    const composer = steps.find((s) => s.kind === "composer");
    expect(composer).toMatchObject({
      kind: "composer",
      model: "gpt-4o",
      latencyMs: 800,
      messages: ["Hola, el modelo cuesta $325,000"],
    });
    expect((composer as { costUsd: number | null }).costUsd).toBeCloseTo(0.0008, 6);
  });

  it("emits transition step when stage changed", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "transition")).toMatchObject({
      kind: "transition",
      from: "lead_warm",
      to: "quote_sent",
    });
  });

  it("emits knowledge step from composer_input.action_payload (FAQ matches)", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      composer_input: {
        action: "lookup_faq",
        action_payload: {
          matches: [
            { pregunta: "¿Aceptan transferencia?", respuesta: "Sí, también.", score: 0.84 },
            { pregunta: "¿Cuál es el horario?", respuesta: "9 a 18.", score: 0.71 },
          ],
        },
      },
    };
    const kb = buildTurnStory(trace).find((s) => s.kind === "knowledge");
    expect(kb).toMatchObject({ kind: "knowledge", action: "lookup_faq" });
    expect((kb as { hits: { title: string; score: number }[] }).hits).toHaveLength(2);
    expect((kb as { hits: { title: string }[] }).hits[0]?.title).toContain("transferencia");
  });

  it("emits knowledge step with emptyHint when the tool returned no data", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      composer_input: {
        action: "lookup_faq",
        action_payload: { hint: "no FAQ above similarity threshold 0.5" },
      },
    };
    const kb = buildTurnStory(trace).find((s) => s.kind === "knowledge");
    expect(kb).toMatchObject({ kind: "knowledge", action: "lookup_faq" });
    expect((kb as { emptyHint?: string }).emptyHint).toContain("similarity");
  });

  it("flags hasMedia when inbound_text is null but a message id exists", () => {
    const trace = { ...baseTrace, inbound_text: null };
    const steps = buildTurnStory(trace);
    expect(steps[0]).toMatchObject({
      kind: "inbound",
      text: null,
      hasMedia: true,
    });
  });

  it("skips nlu step when nlu_output is null and there is no nlu_model", () => {
    const trace = { ...baseTrace, nlu_output: null, nlu_model: null };
    const steps = buildTurnStory(trace);
    expect(steps.find((s) => s.kind === "nlu")).toBeUndefined();
  });

  it("skips transition when stage_transition is null", () => {
    const trace = { ...baseTrace, stage_transition: null };
    const steps = buildTurnStory(trace);
    expect(steps.find((s) => s.kind === "transition")).toBeUndefined();
  });

  it("uses migration-045 router_trigger over the heuristic rationale", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      router_trigger: "doc_attachment:has_attachment",
    };
    const mode = buildTurnStory(trace).find((s) => s.kind === "mode");
    expect((mode as { rationale: string | null }).rationale).toContain("doc_attachment");
    expect((mode as { rationale: string | null }).rationale).toContain("has_attachment");
  });

  it("reads knowledge from migration-045 kb_evidence column when present", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      kb_evidence: {
        action: "lookup_faq",
        hits: [
          {
            source_type: "faq",
            source_id: "00000000-0000-0000-0000-0000000000aa",
            collection_id: "00000000-0000-0000-0000-0000000000bb",
            title: "¿Cuál es el horario?",
            preview: "Lunes a sábado 9 a 18.",
            score: 0.81,
          },
        ],
      },
    };
    const kb = buildTurnStory(trace).find((s) => s.kind === "knowledge");
    expect(kb).toMatchObject({ kind: "knowledge", action: "lookup_faq" });
    const hits = (kb as { hits: { title: string; externalId?: string }[] }).hits;
    expect(hits).toHaveLength(1);
    expect(hits[0]?.title).toContain("horario");
    expect(hits[0]?.externalId).toBe("00000000-0000-0000-0000-0000000000aa");
  });

  it("exposes raw_llm_response on the composer step when set", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      raw_llm_response: '{"messages":["Hola, el modelo cuesta $325,000"]}',
    };
    const composer = buildTurnStory(trace).find((s) => s.kind === "composer");
    expect((composer as { rawLlmResponse: string | null }).rawLlmResponse).toContain("$325,000");
  });
});

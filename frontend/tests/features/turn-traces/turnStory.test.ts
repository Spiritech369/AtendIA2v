import { describe, expect, it } from "vitest";

import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { buildTurnStory } from "@/features/turn-traces/lib/turnStory";

const baseTrace: TurnTraceDetail = {
  id: "t1",
  conversation_id: "c1",
  turn_number: 1,
  inbound_message_id: "m1",
  inbound_preview: "¿Cuánto cuesta el Civic?",
  flow_mode: "SALES",
  nlu_model: "gpt-4o-mini",
  composer_model: "gpt-4o",
  total_cost_usd: "0.001",
  total_latency_ms: 1200,
  bot_paused: false,
  created_at: "2026-05-12T00:00:00Z",
  inbound_text: "¿Cuánto cuesta el Civic?",
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
  composer_input: null,
  composer_output: {
    messages: ["Hola, el Civic cuesta $325,000"],
    pending_confirmation_set: null,
  },
  composer_tokens_in: null,
  composer_tokens_out: null,
  composer_cost_usd: null,
  composer_latency_ms: 800,
  vision_cost_usd: null,
  vision_latency_ms: null,
  tool_cost_usd: null,
  state_before: { current_stage: "lead_warm" },
  state_after: { current_stage: "quote_sent" },
  stage_transition: "lead_warm → quote_sent",
  outbound_messages: [{ text: "Hola, el Civic cuesta $325,000" }],
  errors: null,
  tool_calls: [],
};

describe("buildTurnStory", () => {
  it("emits inbound step from inbound_text", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps[0]).toMatchObject({
      kind: "inbound",
      text: "¿Cuánto cuesta el Civic?",
    });
  });

  it("emits nlu step with intent + extracted entities", () => {
    const steps = buildTurnStory(baseTrace);
    const nlu = steps.find((s) => s.kind === "nlu");
    expect(nlu).toMatchObject({
      kind: "nlu",
      intent: "ask_price",
      extracted: { brand: "Honda", model: "Civic" },
    });
  });

  it("emits mode step from flow_mode", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "mode")).toMatchObject({
      kind: "mode",
      mode: "SALES",
    });
  });

  it("emits outbound step with previews", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "outbound")).toMatchObject({
      kind: "outbound",
      count: 1,
      previews: ["Hola, el Civic cuesta $325,000"],
    });
  });

  it("emits transition step when stage changed", () => {
    const steps = buildTurnStory(baseTrace);
    expect(steps.find((s) => s.kind === "transition")).toMatchObject({
      kind: "transition",
      from: "lead_warm",
      to: "quote_sent",
    });
  });

  it("emits tool step per tool call with summary", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      tool_calls: [
        {
          id: "tc1",
          tool_name: "search_catalog",
          input_payload: { query: "Civic" },
          output_payload: {
            results: [{ name: "Honda Civic 2024", price: 325000 }],
          },
          latency_ms: 50,
          error: null,
          called_at: "2026-05-12T00:00:01Z",
        },
      ],
    };
    const steps = buildTurnStory(trace);
    const tool = steps.find((s) => s.kind === "tool");
    expect(tool).toMatchObject({ kind: "tool", toolName: "search_catalog" });
    expect((tool as { kind: "tool"; summary: string }).summary).toContain("Civic");
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

  it("skips nlu step when nlu_output is null", () => {
    const trace = { ...baseTrace, nlu_output: null };
    const steps = buildTurnStory(trace);
    expect(steps.find((s) => s.kind === "nlu")).toBeUndefined();
  });

  it("skips transition when stage_transition is null", () => {
    const trace = { ...baseTrace, stage_transition: null };
    const steps = buildTurnStory(trace);
    expect(steps.find((s) => s.kind === "transition")).toBeUndefined();
  });

  it("handles tool errors by populating the error field", () => {
    const trace: TurnTraceDetail = {
      ...baseTrace,
      tool_calls: [
        {
          id: "tc",
          tool_name: "quote",
          input_payload: {},
          output_payload: null,
          latency_ms: 10,
          error: "missing SKU",
          called_at: "2026-05-12T00:00:01Z",
        },
      ],
    };
    const tool = buildTurnStory(trace).find((s) => s.kind === "tool");
    expect(tool).toMatchObject({ kind: "tool", error: "missing SKU" });
  });
});

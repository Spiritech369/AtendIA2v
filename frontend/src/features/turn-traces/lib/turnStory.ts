import type { TurnTraceDetail } from "@/features/turn-traces/api";
import {
  extractKnowledge,
  type KnowledgeBlock,
  outboundPreviews,
  readIntent,
} from "@/features/turn-traces/lib/turnAnalysis";

// Story steps are the narrative the operator reads top-down. We build
// one per logical stage of the turn so the panel can render a
// vertical timeline instead of a flat key-value dump.
//
// Vertical-agnostic: no step type knows about credit, motorcycles,
// clinics, etc. Labels in the UI come from `intent`, `mode`, `action`
// and from the tenant's own state keys.

export type StoryStep =
  | {
      kind: "inbound";
      text: string | null;
      hasMedia: boolean;
      turnNumber: number;
      totalTurns: number | null;
    }
  | {
      kind: "nlu";
      intent: string | null;
      confidence: number | null;
      entityCount: number;
    }
  | { kind: "mode"; mode: string | null; rationale: string | null }
  | {
      kind: "knowledge";
      action: string | null;
      hits: KnowledgeBlock["hits"];
      emptyHint?: string;
    }
  | {
      kind: "composer";
      model: string | null;
      latencyMs: number | null;
      costUsd: number | null;
      messages: string[];
      pendingConfirmation: string | null;
      // Migration 045 — raw OpenAI text. When present and different from
      // the parsed messages, the composer step renders a diff toggle.
      rawLlmResponse: string | null;
    }
  | {
      kind: "transition";
      from: string;
      to: string;
    };

function parseTransition(t: string | null): { from: string; to: string } | null {
  if (!t) return null;
  const m = t.match(/^(.+?)\s*(?:→|->)\s*(.+)$/);
  if (m?.[1] && m[2]) return { from: m[1].trim(), to: m[2].trim() };
  return null;
}

// Migration 045 persists `router_trigger` as `"<rule_id>:<trigger_type>"`.
// When present, parse it into a human-readable line. Returns null for
// legacy rows so the heuristic fallback below kicks in.
function readRouterTrigger(trace: TurnTraceDetail): string | null {
  if (!trace.router_trigger) return null;
  const sep = trace.router_trigger.indexOf(":");
  if (sep < 0) return trace.router_trigger;
  const ruleId = trace.router_trigger.slice(0, sep);
  const triggerType = trace.router_trigger.slice(sep + 1);
  return `regla "${ruleId}" (${triggerType})`;
}

// Best-effort rationale derived from observable signals — used as a
// fallback when router_trigger isn't populated (pre-045 rows).
function deriveModeRationale(trace: TurnTraceDetail): string | null {
  const ci =
    trace.composer_input && typeof trace.composer_input === "object"
      ? (trace.composer_input as Record<string, unknown>)
      : null;
  if (!ci) return null;

  const action = typeof ci.action === "string" ? ci.action : null;
  const visionResult = ci.vision_result;
  const intent = readIntent(trace).intent;
  const pendingConfirmation =
    trace.state_before &&
    typeof trace.state_before === "object" &&
    typeof (trace.state_before as Record<string, unknown>).pending_confirmation === "string"
      ? ((trace.state_before as Record<string, unknown>).pending_confirmation as string)
      : null;

  if (pendingConfirmation) {
    return `confirmación pendiente: "${pendingConfirmation}"`;
  }
  if (visionResult && typeof visionResult === "object") {
    return "el cliente envió un adjunto";
  }
  if (action) {
    return `acción decidida: ${action}`;
  }
  if (intent) {
    return `intent detectado: ${intent}`;
  }
  return null;
}

export function buildTurnStory(
  trace: TurnTraceDetail,
  opts: { totalTurns?: number | null } = {},
): StoryStep[] {
  const steps: StoryStep[] = [];

  steps.push({
    kind: "inbound",
    text: trace.inbound_text,
    hasMedia: !trace.inbound_text && !!trace.inbound_message_id,
    turnNumber: trace.turn_number,
    totalTurns: opts.totalTurns ?? null,
  });

  const { intent, confidence } = readIntent(trace);
  const nluEntities =
    trace.nlu_output &&
    typeof trace.nlu_output === "object" &&
    (trace.nlu_output as { entities?: unknown }).entities &&
    typeof (trace.nlu_output as { entities?: unknown }).entities === "object"
      ? Object.keys((trace.nlu_output as { entities: Record<string, unknown> }).entities)
      : [];

  if (intent || trace.nlu_model) {
    steps.push({
      kind: "nlu",
      intent,
      confidence,
      entityCount: nluEntities.length,
    });
  }

  if (trace.flow_mode) {
    steps.push({
      kind: "mode",
      mode: trace.flow_mode,
      rationale: readRouterTrigger(trace) ?? deriveModeRationale(trace),
    });
  }

  const kb = extractKnowledge(trace);
  if (kb.action || kb.hits.length > 0 || kb.emptyHint) {
    steps.push({
      kind: "knowledge",
      action: kb.action,
      hits: kb.hits,
      emptyHint: kb.emptyHint,
    });
  }

  if (trace.composer_output || trace.composer_model) {
    steps.push({
      kind: "composer",
      model: trace.composer_model,
      latencyMs: trace.composer_latency_ms,
      costUsd: trace.composer_cost_usd != null ? Number(trace.composer_cost_usd) : null,
      messages: outboundPreviews(trace),
      pendingConfirmation:
        trace.composer_output &&
        typeof trace.composer_output === "object" &&
        typeof (trace.composer_output as { pending_confirmation_set?: unknown })
          .pending_confirmation_set === "string"
          ? ((trace.composer_output as Record<string, unknown>).pending_confirmation_set as string)
          : null,
      rawLlmResponse: trace.raw_llm_response,
    });
  }

  const t = parseTransition(trace.stage_transition);
  if (t) steps.push({ kind: "transition", from: t.from, to: t.to });

  return steps;
}

import type { TurnTraceDetail } from "@/features/turn-traces/api";

export type StoryStep =
  | { kind: "inbound"; text: string | null; hasMedia: boolean }
  | {
      kind: "nlu";
      intent: string | null;
      extracted: Record<string, unknown>;
    }
  | { kind: "mode"; mode: string | null }
  | {
      kind: "tool";
      toolName: string;
      summary: string;
      error: string | null;
    }
  | { kind: "composer"; messages: string[] }
  | { kind: "outbound"; count: number; previews: string[] }
  | { kind: "transition"; from: string; to: string };

function extractEntities(nluOutput: unknown): Record<string, unknown> {
  if (!nluOutput || typeof nluOutput !== "object") return {};
  const entities = (nluOutput as { entities?: unknown }).entities;
  if (!entities || typeof entities !== "object") return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entities as Record<string, unknown>)) {
    if (v && typeof v === "object" && "value" in (v as object)) {
      out[k] = (v as { value: unknown }).value;
    } else {
      out[k] = v;
    }
  }
  return out;
}

function summarizeTool(
  name: string,
  input: unknown,
  output: unknown,
): string {
  if (name === "search_catalog" && output && typeof output === "object") {
    const results = (output as { results?: unknown }).results;
    if (Array.isArray(results) && results.length > 0) {
      const first = results[0] as Record<string, unknown>;
      const label = String(first.name ?? first.sku ?? "resultado");
      const price = first.price != null ? ` — $${first.price}` : "";
      return `${results.length} resultado${results.length > 1 ? "s" : ""}: ${label}${price}`;
    }
    if (Array.isArray(results)) return "0 resultados";
  }
  if (name === "lookup_faq" && output && typeof output === "object") {
    const answer = (output as { answer?: unknown }).answer;
    if (typeof answer === "string") {
      return `respuesta: ${answer.slice(0, 60)}${answer.length > 60 ? "…" : ""}`;
    }
  }
  if (name === "quote" && output && typeof output === "object") {
    const total = (output as { total?: unknown }).total;
    if (total != null) return `cotización: $${total}`;
  }
  if (input && typeof input === "object") {
    const entries = Object.entries(input).slice(0, 2);
    return (
      entries.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ") ||
      "(sin datos)"
    );
  }
  return "(sin datos)";
}

function parseTransition(
  t: string | null,
): { from: string; to: string } | null {
  if (!t) return null;
  const m = t.match(/^(.+?)\s*(?:→|->)\s*(.+)$/);
  if (m) return { from: m[1].trim(), to: m[2].trim() };
  return null;
}

function outboundPreviews(messages: unknown): string[] {
  if (!Array.isArray(messages)) return [];
  return messages
    .map((m) => {
      if (typeof m === "string") return m;
      if (m && typeof m === "object" && "text" in m) {
        return String((m as { text: unknown }).text ?? "");
      }
      return "";
    })
    .filter((t) => t.length > 0);
}

export function buildTurnStory(trace: TurnTraceDetail): StoryStep[] {
  const steps: StoryStep[] = [];

  steps.push({
    kind: "inbound",
    text: trace.inbound_text,
    hasMedia: !trace.inbound_text && !!trace.inbound_message_id,
  });

  if (trace.nlu_output) {
    const out = trace.nlu_output as Record<string, unknown>;
    steps.push({
      kind: "nlu",
      intent: typeof out.intent === "string" ? out.intent : null,
      extracted: extractEntities(trace.nlu_output),
    });
  }

  if (trace.flow_mode) {
    steps.push({ kind: "mode", mode: trace.flow_mode });
  }

  for (const tc of trace.tool_calls ?? []) {
    steps.push({
      kind: "tool",
      toolName: tc.tool_name,
      summary: summarizeTool(tc.tool_name, tc.input_payload, tc.output_payload),
      error: tc.error,
    });
  }

  if (trace.composer_output) {
    const out = trace.composer_output as Record<string, unknown>;
    const messages = Array.isArray(out.messages)
      ? out.messages.map((m) => String(m))
      : [];
    if (messages.length > 0) steps.push({ kind: "composer", messages });
  }

  const previews = outboundPreviews(trace.outbound_messages);
  if (previews.length > 0) {
    steps.push({ kind: "outbound", count: previews.length, previews });
  }

  const t = parseTransition(trace.stage_transition);
  if (t) steps.push({ kind: "transition", from: t.from, to: t.to });

  return steps;
}

// Derived shapes for the DebugPanel rebuild. Pure: takes the raw
// TurnTraceDetail JSON and projects the bits the UI cares about so the
// React tree can stay declarative.
//
// Vertical-agnostic by construction: nothing in here knows about
// motorcycles, credit, clinics, or any particular tenant taxonomy.
// Every label comes from the trace itself (state keys, action names,
// payload structure).
import type { TurnTraceDetail } from "@/features/turn-traces/api";

// ── Entities ────────────────────────────────────────────────────────

export type EntityStatus = "extracted_saved" | "extracted_not_saved" | "previously_saved";

export interface ClassifiedEntity {
  field: string;
  value: unknown;
  status: EntityStatus;
  confidence?: number;
  sourceTurn?: number;
}

interface ExtractedFieldShape {
  value: unknown;
  confidence?: number;
  source_turn?: number;
}

function readExtractedMap(
  state: Record<string, unknown> | null,
): Record<string, ExtractedFieldShape> {
  if (!state || typeof state !== "object") return {};
  const ed = (state as { extracted_data?: unknown }).extracted_data;
  if (!ed || typeof ed !== "object") return {};
  const out: Record<string, ExtractedFieldShape> = {};
  for (const [k, v] of Object.entries(ed as Record<string, unknown>)) {
    if (v && typeof v === "object" && "value" in (v as object)) {
      out[k] = v as ExtractedFieldShape;
    } else {
      out[k] = { value: v };
    }
  }
  return out;
}

function readNluEntities(nluOutput: Record<string, unknown> | null): Record<string, unknown> {
  if (!nluOutput || typeof nluOutput !== "object") return {};
  const e = (nluOutput as { entities?: unknown }).entities;
  if (!e || typeof e !== "object") return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(e as Record<string, unknown>)) {
    if (v && typeof v === "object" && "value" in (v as object)) {
      out[k] = (v as { value: unknown }).value;
    } else {
      out[k] = v;
    }
  }
  return out;
}

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a == null || b == null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

export function classifyEntities(trace: TurnTraceDetail): ClassifiedEntity[] {
  const turn = trace.turn_number;
  const nlu = readNluEntities(trace.nlu_output);
  const after = readExtractedMap(trace.state_after);

  const out: ClassifiedEntity[] = [];

  // What NLU said this turn → saved or not.
  for (const [k, v] of Object.entries(nlu)) {
    const saved = after[k];
    if (saved && sameValue(saved.value, v)) {
      out.push({
        field: k,
        value: v,
        status: "extracted_saved",
        confidence: saved.confidence,
        sourceTurn: saved.source_turn,
      });
    } else {
      out.push({ field: k, value: v, status: "extracted_not_saved" });
    }
  }

  // Fields saved earlier that NLU didn't touch this turn — show for context.
  for (const [k, ef] of Object.entries(after)) {
    if (k in nlu) continue;
    if (ef.source_turn != null && ef.source_turn < turn) {
      out.push({
        field: k,
        value: ef.value,
        status: "previously_saved",
        confidence: ef.confidence,
        sourceTurn: ef.source_turn,
      });
    }
  }

  return out;
}

// ── Knowledge / KB hits ─────────────────────────────────────────────
// Migration 045 ships a dedicated `kb_evidence` JSONB column populated by
// the runner with normalized hits + their ids/collection_id. We prefer
// that field when present (newer rows). For legacy rows we fall back to
// reading `composer_input.action_payload` like before — the `tool_calls`
// table is empty in production because the runner calls
// lookup_faq / search_catalog directly.

export type KnowledgeSource = "faq" | "catalog" | "quote";

export interface KnowledgeHit {
  source: KnowledgeSource;
  /** Free-text label the operator should recognize (FAQ question, SKU, etc.). */
  title: string;
  /** Long-form preview (FAQ answer, product description) — optional. */
  preview?: string;
  /** Cosine similarity in [0, 1] when the runner reports it. */
  score?: number;
  /** Stable identifier the operator can copy to find the row in KB. */
  externalId?: string;
  /** Collection the hit came from — populated by migration 045. */
  collectionId?: string;
}

export interface KnowledgeBlock {
  action: string | null;
  hits: KnowledgeHit[];
  /** Set when the tool returned ToolNoDataResult — gives the operator a hint. */
  emptyHint?: string;
}

function readComposerInput(trace: TurnTraceDetail): Record<string, unknown> | null {
  if (!trace.composer_input || typeof trace.composer_input !== "object") return null;
  return trace.composer_input as Record<string, unknown>;
}

function readAction(trace: TurnTraceDetail): string | null {
  const ci = readComposerInput(trace);
  if (!ci) return null;
  const a = ci.action;
  return typeof a === "string" ? a : null;
}

function readActionPayload(trace: TurnTraceDetail): Record<string, unknown> | null {
  const ci = readComposerInput(trace);
  if (!ci) return null;
  const ap = ci.action_payload;
  if (!ap || typeof ap !== "object") return null;
  return ap as Record<string, unknown>;
}

export function extractKnowledge(trace: TurnTraceDetail): KnowledgeBlock {
  // Migration 045 — when the runner-built kb_evidence column is present,
  // use it. It's already normalized and carries source ids + collection
  // metadata for deep-links.
  if (trace.kb_evidence) {
    const ev = trace.kb_evidence;
    const hits: KnowledgeHit[] = ev.hits.map((h) => ({
      source: h.source_type,
      title: h.title ?? "(sin título)",
      preview: h.preview ?? undefined,
      score: h.score ?? undefined,
      externalId: h.source_id ?? undefined,
      collectionId: h.collection_id ?? undefined,
    }));
    return {
      action: ev.action ?? null,
      hits,
      emptyHint: ev.empty_hint ?? undefined,
    };
  }

  // Legacy path — pre-045 rows. Re-derive from composer_input.action_payload.
  const action = readAction(trace);
  const payload = readActionPayload(trace);
  if (!payload) return { action, hits: [] };

  if (typeof payload.hint === "string") {
    return { action, hits: [], emptyHint: payload.hint };
  }

  const hits: KnowledgeHit[] = [];

  if (Array.isArray(payload.matches)) {
    for (const m of payload.matches) {
      if (!m || typeof m !== "object") continue;
      const mm = m as Record<string, unknown>;
      hits.push({
        source: "faq",
        title: typeof mm.pregunta === "string" ? mm.pregunta : "(FAQ sin pregunta)",
        preview: typeof mm.respuesta === "string" ? mm.respuesta : undefined,
        score: typeof mm.score === "number" ? mm.score : undefined,
      });
    }
  }

  if (Array.isArray(payload.results)) {
    for (const r of payload.results) {
      if (!r || typeof r !== "object") continue;
      const rr = r as Record<string, unknown>;
      const sku = typeof rr.sku === "string" ? rr.sku : undefined;
      const name = typeof rr.name === "string" ? rr.name : undefined;
      const title = name ?? sku ?? "(producto sin nombre)";
      const price = typeof rr.price === "number" ? `$${rr.price}` : undefined;
      hits.push({
        source: "catalog",
        title,
        preview: price,
        score: typeof rr.score === "number" ? rr.score : undefined,
        externalId: sku,
      });
    }
  }

  // Quote results are a single record, not an array. Show as one card.
  if (action === "quote" && hits.length === 0 && payload.sku) {
    const sku = typeof payload.sku === "string" ? payload.sku : undefined;
    const modelo = typeof payload.modelo === "string" ? payload.modelo : undefined;
    hits.push({
      source: "quote",
      title: modelo ?? sku ?? "(cotización)",
      preview: sku ? `SKU ${sku}` : undefined,
      externalId: sku,
    });
  }

  return { action, hits };
}

// ── State diff (git-style) ──────────────────────────────────────────

export type ChangeKind = "added" | "removed" | "changed" | "stage";

export interface StateChange {
  kind: ChangeKind;
  field: string;
  before?: unknown;
  after?: unknown;
}

function readScalar(state: Record<string, unknown> | null, key: string): unknown {
  return state && typeof state === "object" ? (state as Record<string, unknown>)[key] : undefined;
}

function readExtractedValues(state: Record<string, unknown> | null): Record<string, unknown> {
  const map = readExtractedMap(state);
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(map)) out[k] = v.value;
  return out;
}

export function diffState(trace: TurnTraceDetail): StateChange[] {
  const changes: StateChange[] = [];

  const stageBefore = readScalar(trace.state_before, "current_stage");
  const stageAfter = readScalar(trace.state_after, "current_stage");
  if (stageBefore !== stageAfter && (stageBefore != null || stageAfter != null)) {
    changes.push({
      kind: "stage",
      field: "current_stage",
      before: stageBefore,
      after: stageAfter,
    });
  }

  const before = readExtractedValues(trace.state_before);
  const after = readExtractedValues(trace.state_after);
  const allKeys = new Set<string>([...Object.keys(before), ...Object.keys(after)]);
  for (const k of allKeys) {
    const b = before[k];
    const a = after[k];
    if (sameValue(a, b)) continue;
    if (b === undefined) changes.push({ kind: "added", field: k, after: a });
    else if (a === undefined) changes.push({ kind: "removed", field: k, before: b });
    else changes.push({ kind: "changed", field: k, before: b, after: a });
  }

  // pending_confirmation transitions matter — operators need to see them.
  const pcBefore = readScalar(trace.state_before, "pending_confirmation");
  const pcAfter = readScalar(trace.state_after, "pending_confirmation");
  if (pcBefore !== pcAfter && (pcBefore != null || pcAfter != null)) {
    changes.push({
      kind: "changed",
      field: "pending_confirmation",
      before: pcBefore,
      after: pcAfter,
    });
  }

  return changes;
}

// ── Latency + cost breakdown ────────────────────────────────────────

export interface LatencySlice {
  label: string;
  ms: number;
  /** Tailwind color class — caller picks the palette. */
  classes: string;
}

export function latencySlices(trace: TurnTraceDetail): {
  slices: LatencySlice[];
  totalMs: number;
  accountedMs: number;
} {
  const slices: LatencySlice[] = [];
  if (trace.nlu_latency_ms != null && trace.nlu_latency_ms > 0) {
    slices.push({ label: "NLU", ms: trace.nlu_latency_ms, classes: "bg-sky-500" });
  }
  if (trace.composer_latency_ms != null && trace.composer_latency_ms > 0) {
    slices.push({ label: "Composer", ms: trace.composer_latency_ms, classes: "bg-violet-500" });
  }
  if (trace.vision_latency_ms != null && trace.vision_latency_ms > 0) {
    slices.push({ label: "Vision", ms: trace.vision_latency_ms, classes: "bg-fuchsia-500" });
  }
  const totalMs = trace.total_latency_ms ?? slices.reduce((a, s) => a + s.ms, 0);
  const accountedMs = slices.reduce((a, s) => a + s.ms, 0);
  const otherMs = Math.max(0, totalMs - accountedMs);
  if (otherMs > 0 && slices.length > 0) {
    slices.push({ label: "Otros", ms: otherMs, classes: "bg-slate-400" });
  }
  return { slices, totalMs, accountedMs };
}

export interface CostSlice {
  label: string;
  usd: number;
  classes: string;
}

export function costSlices(trace: TurnTraceDetail): { slices: CostSlice[]; totalUsd: number } {
  const slices: CostSlice[] = [];
  const push = (label: string, raw: string | null, classes: string) => {
    if (raw == null) return;
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) slices.push({ label, usd: n, classes });
  };
  push("NLU", trace.nlu_cost_usd, "bg-sky-500");
  push("Composer", trace.composer_cost_usd, "bg-violet-500");
  push("Vision", trace.vision_cost_usd, "bg-fuchsia-500");
  push("Tools", trace.tool_cost_usd, "bg-amber-500");
  const totalUsd = Number(trace.total_cost_usd ?? "0");
  return { slices, totalUsd: Number.isFinite(totalUsd) ? totalUsd : 0 };
}

// ── Intent + anomaly hints ──────────────────────────────────────────

export function readIntent(trace: TurnTraceDetail): {
  intent: string | null;
  confidence: number | null;
} {
  if (!trace.nlu_output || typeof trace.nlu_output !== "object") {
    return { intent: null, confidence: null };
  }
  const o = trace.nlu_output as Record<string, unknown>;
  const intent = typeof o.intent === "string" ? o.intent : null;
  const conf = typeof o.confidence === "number" ? o.confidence : null;
  return { intent, confidence: conf };
}

export type AnomalyKind = "slow" | "low_confidence" | "errors" | "no_composer" | "bot_paused";

export interface Anomaly {
  kind: AnomalyKind;
  label: string;
  detail?: string;
}

// Static thresholds for the first cut. Per-tenant baselines belong in
// migration 021; until then, anything above 5s is "lento" and any
// confidence under 0.6 is "baja". These map roughly to what an operator
// would flag manually.
const SLOW_THRESHOLD_MS = 5000;
const LOW_CONFIDENCE_THRESHOLD = 0.6;

export function detectAnomalies(trace: TurnTraceDetail): Anomaly[] {
  const out: Anomaly[] = [];
  if (trace.bot_paused) {
    out.push({ kind: "bot_paused", label: "Operador controlaba" });
  }
  if (trace.total_latency_ms != null && trace.total_latency_ms > SLOW_THRESHOLD_MS) {
    out.push({
      kind: "slow",
      label: "Lento",
      detail: `${trace.total_latency_ms}ms supera el umbral de ${SLOW_THRESHOLD_MS}ms`,
    });
  }
  const { confidence } = readIntent(trace);
  if (confidence != null && confidence < LOW_CONFIDENCE_THRESHOLD) {
    out.push({
      kind: "low_confidence",
      label: "Baja confianza",
      detail: `${Math.round(confidence * 100)}% (umbral ${Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}%)`,
    });
  }
  const errs = trace.errors ?? [];
  if (errs.length > 0) {
    out.push({ kind: "errors", label: `${errs.length} error${errs.length > 1 ? "es" : ""}` });
  }
  if (!trace.composer_output && !trace.bot_paused) {
    out.push({ kind: "no_composer", label: "Sin respuesta del bot" });
  }
  return out;
}

// ── Fact pack: what the composer actually saw ────────────────────────

export interface FactPack {
  brandFacts: Record<string, unknown>;
  extractedData: Record<string, unknown>;
  visionResult: Record<string, unknown> | null;
  actionPayload: Record<string, unknown> | null;
}

export function readFactPack(trace: TurnTraceDetail): FactPack {
  const ci = readComposerInput(trace);
  if (!ci) {
    return { brandFacts: {}, extractedData: {}, visionResult: null, actionPayload: null };
  }
  const bf = ci.brand_facts;
  const ed = ci.extracted_data;
  const vr = ci.vision_result;
  const ap = ci.action_payload;
  return {
    brandFacts: bf && typeof bf === "object" ? (bf as Record<string, unknown>) : {},
    extractedData: ed && typeof ed === "object" ? (ed as Record<string, unknown>) : {},
    visionResult: vr && typeof vr === "object" ? (vr as Record<string, unknown>) : null,
    actionPayload: ap && typeof ap === "object" ? (ap as Record<string, unknown>) : null,
  };
}

// ── Actions (composer_output.action_payload) ────────────────────────

export interface ActionItem {
  name: string;
  preview: string;
  raw: unknown;
}

export function analyzeActions(trace: TurnTraceDetail): ActionItem[] {
  const co = trace.composer_output as { action_payload?: Record<string, unknown> } | null;
  const payload = co?.action_payload;
  if (!payload || typeof payload !== "object") return [];
  return Object.entries(payload).map(([name, raw]) => ({
    name,
    preview: previewForAction(name, raw),
    raw,
  }));
}

function previewForAction(name: string, raw: unknown): string {
  if (raw == null || typeof raw !== "object") return String(raw ?? "");
  const obj = raw as Record<string, unknown>;
  if (name === "quote") {
    return `plan=${obj.plan} · monto=${obj.monto_mensual} · ${obj.plazo_meses}m`;
  }
  if (name === "lookup_faq") {
    const q = String(obj.question ?? "");
    return q.length > 60 ? `${q.slice(0, 60)}…` : q;
  }
  // Fallback: first 2 key/value pairs joined.
  return Object.entries(obj)
    .slice(0, 2)
    .map(([k, v]) => `${k}=${v}`)
    .join(" · ");
}

// ── Outbound preview ────────────────────────────────────────────────

export function outboundPreviews(trace: TurnTraceDetail): string[] {
  const out = trace.composer_output;
  if (!out || typeof out !== "object") return [];
  const m = (out as { messages?: unknown }).messages;
  if (!Array.isArray(m)) return [];
  return m.map((x) => String(x)).filter((s) => s.length > 0);
}

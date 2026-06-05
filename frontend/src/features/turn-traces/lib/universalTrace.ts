import type { ConversationDetail } from "@/features/conversations/api";
import type { TurnTraceDetail } from "@/features/turn-traces/api";

export type FieldDecisionStatus =
  | "validated"
  | "proposed"
  | "needs_review"
  | "rejected"
  | "blocked";

export interface TenantFieldView {
  key: string;
  label: string;
  value: unknown;
  status: FieldDecisionStatus;
  group: string;
  domainRole: string | null;
  displayFormat: string | null;
  source: string | null;
  writer: string | null;
  confidence: number | null;
  lastTraceId: string | null;
  evidenceRefs: string[];
}

export interface UniversalTraceRecord {
  trace_version?: string;
  turn_id?: string | null;
  tenant_id?: string | null;
  agent_id?: string | null;
  conversation_id?: string | null;
  contact_id?: string | null;
  domain?: string | null;
  input?: Record<string, unknown>;
  gpt_understanding?: Record<string, unknown>;
  gpt_proposed?: Record<string, unknown>;
  mandatory_tool_decisions?: Array<Record<string, unknown>>;
  tool_results?: Array<Record<string, unknown>>;
  atendia_validation?: Record<string, unknown>;
  state_changes?: Record<string, unknown>;
  lifecycle?: Record<string, unknown>;
  business_events?: Array<Record<string, unknown>>;
  workflow_results?: Array<Record<string, unknown>>;
  guards?: Array<Record<string, unknown>>;
  provider?: Record<string, unknown>;
  final_output?: Record<string, unknown>;
  audit?: Record<string, unknown>;
}

export function normalizeTenantFields(
  fields: ConversationDetail["customer_fields"] | undefined,
): TenantFieldView[] {
  return (fields ?? [])
    .filter((field) => !field.is_debug)
    .map((field) => ({
      key: field.key,
      label: field.label || field.key,
      value: field.value,
      status: normalizeFieldStatus(field.status, field.value),
      group: field.group || field.domain_role || "general",
      domainRole: field.domain_role ?? null,
      displayFormat: field.display_format ?? field.render_mode ?? null,
      source: field.source ?? null,
      writer: field.writer ?? null,
      confidence: normalizeConfidence(field.confidence),
      lastTraceId: field.last_trace_id ?? null,
      evidenceRefs: normalizeEvidenceRefs(field.evidence_refs, field.evidence_id),
    }))
    .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
}

export function hasDeclarativeTenantFields(fields: TenantFieldView[]): boolean {
  return fields.some(
    (field) =>
      Boolean(field.domainRole) ||
      Boolean(field.source) ||
      Boolean(field.writer) ||
      field.status !== "validated",
  );
}

export function readUniversalTurnTrace(trace: TurnTraceDetail): UniversalTraceRecord | null {
  const direct = asRecord(trace.trace_metadata)?.universal_turn_trace;
  if (isUniversalTrace(direct)) return direct;

  const composerOutput = asRecord(trace.composer_output);
  const composerMetadata = asRecord(composerOutput?.trace_metadata);
  if (isUniversalTrace(composerMetadata?.universal_turn_trace)) {
    return composerMetadata.universal_turn_trace;
  }

  const stateAfter = asRecord(trace.state_after);
  const stateMetadata = asRecord(stateAfter?.trace_metadata);
  if (isUniversalTrace(stateMetadata?.universal_turn_trace)) {
    return stateMetadata.universal_turn_trace;
  }

  return null;
}

export function universalWhySummary(trace: UniversalTraceRecord): string[] {
  const finalOutput = asRecord(trace.final_output);
  const understanding = asRecord(trace.gpt_understanding);
  const proposed = asRecord(trace.gpt_proposed);
  const validation = asRecord(trace.atendia_validation);
  const stateWriter = asRecord(validation?.state_writer);
  const mandatory = asRecord(validation?.mandatory_tool_decisions)
    ? []
    : asRecordArray(trace.mandatory_tool_decisions);
  const guards = asRecordArray(trace.guards);

  const lines = [
    `GPT entendio: ${formatValue(understanding?.customer_goal ?? understanding?.next_best_action ?? "mensaje del cliente")}.`,
  ];
  const proposedCount = asRecordArray(proposed?.state_changes).length;
  if (proposedCount > 0) {
    lines.push(`GPT propuso ${proposedCount} cambio${proposedCount === 1 ? "" : "s"} de estado.`);
  }
  const missingTools = mandatory.filter((decision) => String(decision.status) === "missing");
  if (missingTools.length > 0) {
    lines.push(`AtendIA exigio ${missingTools.length} tool obligatoria antes de confirmar datos.`);
  }
  const accepted = asRecordArray(stateWriter?.accepted).length;
  const blocked = asRecordArray(stateWriter?.blocked).length;
  const needsReview = asRecordArray(stateWriter?.needs_review).length;
  if (accepted || blocked || needsReview) {
    lines.push(
      `StateWriter valido ${accepted}, bloqueo ${blocked} y mando a revision ${needsReview}.`,
    );
  }
  const rewrittenGuard = guards.find((guard) => String(guard.result) === "rewrote");
  if (rewrittenGuard) {
    lines.push(
      `Un guard ajusto la respuesta: ${formatValue(rewrittenGuard.reason ?? "sin motivo")}.`,
    );
  }
  if (typeof finalOutput?.final_message === "string") {
    lines.push("El cliente vio el mensaje final de TurnOutput.final_message.");
  }
  return lines;
}

export function fieldStatusMeta(status: FieldDecisionStatus): {
  label: string;
  className: string;
} {
  switch (status) {
    case "validated":
      return {
        label: "validated",
        className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
      };
    case "proposed":
      return {
        label: "proposed",
        className: "border-sky-500/40 bg-sky-500/10 text-sky-700",
      };
    case "needs_review":
      return {
        label: "needs_review",
        className: "border-amber-500/40 bg-amber-500/10 text-amber-700",
      };
    case "rejected":
      return {
        label: "rejected",
        className: "border-rose-500/40 bg-rose-500/10 text-rose-700",
      };
    case "blocked":
      return {
        label: "blocked",
        className: "border-red-500/40 bg-red-500/10 text-red-700",
      };
  }
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(asRecord(item)))
    : [];
}

export function formatValue(value: unknown, maxLength = 80): string {
  if (value == null || value === "") return "sin dato";
  if (typeof value === "string") {
    return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const serialized = JSON.stringify(value);
    return serialized.length > maxLength ? `${serialized.slice(0, maxLength)}...` : serialized;
  } catch {
    return String(value);
  }
}

function isUniversalTrace(value: unknown): value is UniversalTraceRecord {
  const record = asRecord(value);
  return Boolean(record?.trace_version || record?.final_output || record?.atendia_validation);
}

function normalizeFieldStatus(raw: unknown, value: unknown): FieldDecisionStatus {
  const status = String(raw ?? "").toLowerCase();
  if (status === "validated" || status === "accepted") return "validated";
  if (status === "proposed" || status === "pending") return "proposed";
  if (status === "needs_review" || status === "review") return "needs_review";
  if (status === "rejected") return "rejected";
  if (status === "blocked") return "blocked";
  return value == null || value === "" ? "proposed" : "validated";
}

function normalizeConfidence(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function normalizeEvidenceRefs(value: unknown, evidenceId: unknown): string[] {
  const refs = Array.isArray(value) ? value.map(String).filter(Boolean) : [];
  if (typeof evidenceId === "string" && evidenceId.trim()) refs.push(evidenceId);
  return [...new Set(refs)];
}

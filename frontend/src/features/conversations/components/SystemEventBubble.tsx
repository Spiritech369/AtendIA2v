import {
  ArrowRightLeft,
  CheckCircle2,
  CircleSlash,
  FileCheck,
  FileX,
  Info,
  Library,
  PauseCircle,
  UserCog,
  Workflow,
  XCircle,
} from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type EventVariant =
  | "field_updated"
  | "stage_changed"
  | "document_accepted"
  | "document_rejected"
  | "bot_paused"
  | "human_handoff_requested"
  | "assignment_changed"
  | "workflow_triggered"
  | "workflow_completed"
  | "knowledge_used"
  | "docs_complete_for_plan"
  | "default";

interface VariantStyle {
  icon: ReactNode;
  pill: string;
}

const VARIANTS: Record<EventVariant, VariantStyle> = {
  field_updated: {
    icon: <Info className="h-3.5 w-3.5" />,
    pill: "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900/40 dark:bg-sky-950/40 dark:text-sky-100",
  },
  stage_changed: {
    icon: <ArrowRightLeft className="h-3.5 w-3.5" />,
    pill: "border-indigo-200 bg-indigo-50 text-indigo-900 dark:border-indigo-900/40 dark:bg-indigo-950/40 dark:text-indigo-100",
  },
  document_accepted: {
    icon: <FileCheck className="h-3.5 w-3.5" />,
    pill: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/40 dark:text-emerald-100",
  },
  document_rejected: {
    icon: <FileX className="h-3.5 w-3.5" />,
    pill: "border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-100",
  },
  bot_paused: {
    icon: <PauseCircle className="h-3.5 w-3.5" />,
    pill: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/40 dark:text-amber-100",
  },
  human_handoff_requested: {
    icon: <UserCog className="h-3.5 w-3.5" />,
    pill: "border-purple-200 bg-purple-50 text-purple-900 dark:border-purple-900/40 dark:bg-purple-950/40 dark:text-purple-100",
  },
  assignment_changed: {
    icon: <UserCog className="h-3.5 w-3.5" />,
    pill: "border-indigo-200 bg-indigo-50 text-indigo-900 dark:border-indigo-900/40 dark:bg-indigo-950/40 dark:text-indigo-100",
  },
  workflow_triggered: {
    icon: <Workflow className="h-3.5 w-3.5" />,
    pill: "border-violet-200 bg-violet-50 text-violet-900 dark:border-violet-900/40 dark:bg-violet-950/40 dark:text-violet-100",
  },
  workflow_completed: {
    icon: <Workflow className="h-3.5 w-3.5" />,
    pill: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/40 dark:bg-emerald-950/40 dark:text-emerald-100",
  },
  knowledge_used: {
    icon: <Library className="h-3.5 w-3.5" />,
    pill: "border-cyan-200 bg-cyan-50 text-cyan-900 dark:border-cyan-900/40 dark:bg-cyan-950/40 dark:text-cyan-100",
  },
  docs_complete_for_plan: {
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    pill: "border-emerald-300 bg-emerald-100 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/60 dark:text-emerald-100",
  },
  default: {
    icon: <CircleSlash className="h-3.5 w-3.5" />,
    pill: "border-muted bg-muted text-muted-foreground",
  },
};

interface Props {
  text: string;
  metadata: Record<string, unknown> | null | undefined;
  sentAt?: string | null;
}

function normalizeSystemText(text: string): string {
  return text.replace(/^sistema:\s*/i, "").trim();
}

function inferEventTypeFromText(text: string): EventVariant {
  const normalized = normalizeSystemText(text).toLowerCase();
  if (normalized.includes("workflow") || normalized.includes("flujo")) {
    if (
      normalized.includes("complet") ||
      normalized.includes("termin") ||
      normalized.includes("finaliz")
    ) {
      return "workflow_completed";
    }
    return "workflow_triggered";
  }
  if (
    normalized.includes("asign") ||
    normalized.includes("desasign") ||
    normalized.includes("handoff")
  ) {
    return "assignment_changed";
  }
  if (
    normalized.includes("knowledge") ||
    normalized.includes("kb") ||
    normalized.includes("base de conocimiento") ||
    normalized.includes("documento")
  ) {
    return "knowledge_used";
  }
  if (normalized.includes("actualizado") || normalized.includes("actualizada")) {
    return "field_updated";
  }
  return "default";
}

function readEventType(metadata: Props["metadata"], text: string): EventVariant {
  if (metadata && typeof metadata === "object") {
    const raw = metadata.event_type;
    if (typeof raw === "string" && raw in VARIANTS) return raw as EventVariant;
  }
  const inferred = inferEventTypeFromText(text);
  if (inferred !== "default") return inferred;
  return "default";
}

function readPayload(metadata: Props["metadata"]): Record<string, unknown> {
  if (!metadata || typeof metadata !== "object") return {};
  const raw = metadata.payload;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
}

function formatConfidence(value: unknown): string | null {
  if (typeof value !== "number") return null;
  return `${Math.round(value * 100)}%`;
}

function formatShortTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("es-MX", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stageText(payload: Record<string, unknown>, sentAt: string | null | undefined): string {
  const fromText = String(payload.from_label || payload.from || "");
  const toText = String(payload.to_label || payload.to || "");
  const reason = typeof payload.reason === "string" ? payload.reason : "";
  const time = formatShortTime(sentAt);
  const parts = ["Sistema"];
  if (time) parts.push(time);
  if (fromText || toText) parts.push(`Etapa: ${fromText || "?"} -> ${toText || "?"}`);
  if (reason) parts.push(`motivo: ${reason}`);
  return parts.join(" · ");
}

function renderDetails(
  variant: EventVariant,
  payload: Record<string, unknown>,
): ReactNode | null {
  if (variant === "field_updated") {
    const { old_value: oldValue, new_value: newValue, confidence, source } = payload;
    const conf = formatConfidence(confidence);
    const parts: string[] = [];
    if (oldValue !== undefined && oldValue !== null && oldValue !== "") {
      parts.push(`${String(oldValue)} → ${String(newValue ?? "")}`);
    }
    if (conf) parts.push(`conf ${conf}`);
    if (typeof source === "string" && source !== "nlu") parts.push(source);
    return parts.length > 0 ? parts.join(" · ") : null;
  }

  if (variant === "document_rejected") {
    const reason = payload.reason;
    return typeof reason === "string" ? reason : null;
  }

  if (variant === "document_accepted") {
    const conf = formatConfidence(payload.confidence);
    return conf ? `conf ${conf}` : null;
  }

  if (
    variant === "bot_paused" ||
    variant === "human_handoff_requested" ||
    variant === "assignment_changed" ||
    variant === "workflow_triggered" ||
    variant === "workflow_completed" ||
    variant === "knowledge_used"
  ) {
    const reason = payload.reason;
    const workflow = payload.workflow_name || payload.workflow || payload.workflow_id;
    const target = payload.assigned_to || payload.user_email || payload.agent_name || payload.agent_id;
    const sources = payload.sources || payload.document || payload.document_id;
    const parts = [workflow, target, sources, reason].filter(
      (value): value is string => typeof value === "string" && value.trim().length > 0,
    );
    return parts.length > 0 ? parts.join(" · ") : null;
  }

  return null;
}

export function SystemEventBubble({ text, metadata, sentAt }: Props) {
  const variant = readEventType(metadata, text);
  const payload = readPayload(metadata);
  const detail = renderDetails(variant, payload);
  const style = VARIANTS[variant];
  const cleanedText = variant === "default" ? text : normalizeSystemText(text);
  const mainText = variant === "stage_changed" ? stageText(payload, sentAt) : cleanedText || text;

  return (
    <div className="flex w-full justify-center">
      <div
        className={cn(
          "inline-flex max-w-[80%] items-start gap-2 rounded-full border px-3 py-1 text-xs",
          style.pill,
        )}
        data-event-type={variant}
      >
        <span className="mt-0.5 shrink-0 opacity-80">{style.icon}</span>
        <div className="min-w-0">
          <div className="leading-tight">{mainText}</div>
          {detail && (
            <div className="mt-0.5 truncate text-[10px] opacity-70">{detail}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export function hasStructuredSystemEvent(
  metadata: Record<string, unknown> | null | undefined,
  text = "",
): boolean {
  if (metadata && typeof metadata === "object" && typeof metadata.event_type === "string") return true;
  return inferEventTypeFromText(text) !== "default";
}

export const SYSTEM_EVENT_ICONS = {
  field_updated: Info,
  stage_changed: ArrowRightLeft,
  document_accepted: FileCheck,
  document_rejected: FileX,
  bot_paused: PauseCircle,
  human_handoff_requested: UserCog,
  assignment_changed: UserCog,
  workflow_triggered: Workflow,
  workflow_completed: Workflow,
  knowledge_used: Library,
  docs_complete_for_plan: CheckCircle2,
  default: XCircle,
};

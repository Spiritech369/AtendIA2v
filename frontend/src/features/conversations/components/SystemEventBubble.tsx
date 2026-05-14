import {
  ArrowRightLeft,
  CheckCircle2,
  CircleSlash,
  FileCheck,
  FileX,
  Info,
  PauseCircle,
  UserCog,
  XCircle,
} from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * SystemEventBubble — renders runner-emitted "Sistema: …" rows inline
 * in the conversation timeline.
 *
 * The backend inserts `messages` rows with `direction='system'` and a
 * `metadata_json` shaped as:
 *
 *   {
 *     event_type: "field_updated" | "stage_changed" |
 *                  "document_accepted" | "document_rejected" |
 *                  "bot_paused" | "human_handoff_requested" |
 *                  "docs_complete_for_plan",
 *     payload: { ...event-specific fields... },
 *     source: "runner"
 *   }
 *
 * If the row has no event_type (legacy / hand-inserted), we fall back to
 * the original plain-italic styling so older traffic doesn't regress.
 *
 * Keep this component dumb on purpose — no fetching, no mutations. The
 * timeline is the single source of truth; we just decorate.
 */

type EventVariant =
  | "field_updated"
  | "stage_changed"
  | "document_accepted"
  | "document_rejected"
  | "bot_paused"
  | "human_handoff_requested"
  | "docs_complete_for_plan"
  | "default";

interface VariantStyle {
  icon: ReactNode;
  /** Tailwind classes applied to the pill wrapper. */
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
}

function readEventType(metadata: Props["metadata"]): EventVariant {
  if (!metadata || typeof metadata !== "object") return "default";
  const raw = (metadata as Record<string, unknown>).event_type;
  if (typeof raw !== "string") return "default";
  if (raw in VARIANTS) return raw as EventVariant;
  return "default";
}

function readPayload(metadata: Props["metadata"]): Record<string, unknown> {
  if (!metadata || typeof metadata !== "object") return {};
  const raw = (metadata as Record<string, unknown>).payload;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
}

function formatConfidence(value: unknown): string | null {
  if (typeof value !== "number") return null;
  return `${Math.round(value * 100)}%`;
}

function renderDetails(
  variant: EventVariant,
  payload: Record<string, unknown>,
): ReactNode | null {
  // Compact secondary line shown beneath the main text. Optional — only
  // appears for variants where the extra context helps the operator
  // (rejected docs need the reason; field updates show old → new).
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

  if (variant === "stage_changed") {
    const { from, to, from_label: fromLabel, to_label: toLabel } = payload;
    const fromText = (fromLabel as string) || (from as string) || "";
    const toText = (toLabel as string) || (to as string) || "";
    return fromText && toText ? `${fromText} → ${toText}` : null;
  }

  if (variant === "bot_paused" || variant === "human_handoff_requested") {
    const reason = payload.reason;
    return typeof reason === "string" ? reason : null;
  }

  return null;
}

export function SystemEventBubble({ text, metadata }: Props) {
  const variant = readEventType(metadata);
  const payload = readPayload(metadata);
  const detail = renderDetails(variant, payload);
  const style = VARIANTS[variant];

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
          <div className="leading-tight">{text}</div>
          {detail && (
            <div className="mt-0.5 truncate text-[10px] opacity-70">{detail}</div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Used by MessageBubble to decide whether to delegate to this component. */
export function hasStructuredSystemEvent(
  metadata: Record<string, unknown> | null | undefined,
): boolean {
  if (!metadata || typeof metadata !== "object") return false;
  return typeof metadata.event_type === "string";
}

/** Re-export for tests that need to assert the lucide icon set used. */
export const SYSTEM_EVENT_ICONS = {
  field_updated: Info,
  stage_changed: ArrowRightLeft,
  document_accepted: FileCheck,
  document_rejected: FileX,
  bot_paused: PauseCircle,
  human_handoff_requested: UserCog,
  docs_complete_for_plan: CheckCircle2,
  default: XCircle,
};

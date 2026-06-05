import { CheckCircle2, Clock3, RotateCcw, ShieldX } from "lucide-react";
import type { ElementType } from "react";

import { Badge } from "@/components/ui/badge";
import {
  asRecord,
  asRecordArray,
  formatValue,
  type UniversalTraceRecord,
} from "@/features/turn-traces/lib/universalTrace";
import { cn } from "@/lib/utils";
import { PanelHeading } from "./DecisionTimeline";

const DECISION_CLASS: Record<string, string> = {
  accepted: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  blocked: "border-red-500/40 bg-red-500/10 text-red-700",
  needs_review: "border-amber-500/40 bg-amber-500/10 text-amber-700",
  invalidated: "border-slate-500/40 bg-slate-500/10 text-slate-700",
};

const DECISION_ICON: Record<string, ElementType> = {
  accepted: CheckCircle2,
  blocked: ShieldX,
  needs_review: Clock3,
  invalidated: RotateCcw,
};

export function StateWriterCards({ trace }: { trace: UniversalTraceRecord }) {
  const state = asRecord(trace.state_changes);
  const rows: Array<Record<string, unknown> & { decision: string }> = [
    ...asRecordArray(state?.accepted).map((item) => ({ ...item, decision: "accepted" })),
    ...asRecordArray(state?.blocked).map((item) => ({ ...item, decision: "blocked" })),
    ...asRecordArray(state?.needs_review).map((item) => ({ ...item, decision: "needs_review" })),
    ...asRecordArray(state?.invalidated_fields).map((item) => ({
      ...item,
      decision: "invalidated",
    })),
  ];
  const summary = asRecord(state?.summary);

  if (rows.length === 0) {
    return (
      <section className="space-y-2">
        <PanelHeading title="StateWriter" />
        <div className="text-xs text-muted-foreground">Sin cambios de estado validados.</div>
      </section>
    );
  }

  return (
    <section className="space-y-2" aria-label="StateWriter cards">
      <PanelHeading
        title="StateWriter"
        badge={
          summary
            ? `accepted ${formatValue(summary.accepted_count)}, blocked ${formatValue(
                summary.blocked_count,
              )}`
            : `${rows.length}`
        }
      />
      <div className="space-y-1.5">
        {rows.map((row) => {
          const decision = String(row.decision ?? "blocked");
          const Icon = DECISION_ICON[decision] ?? ShieldX;
          const key = [row.field ?? row.key, row.decision, row.reason, row.source]
            .map(formatValue)
            .join(":");
          return (
            <div key={key} className="rounded-md border bg-card p-2 text-xs">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium">{formatValue(row.field ?? row.key)}</div>
                  <div className="mt-0.5 break-words text-[12px] text-foreground/90">
                    {formatValue(row.proposed_value ?? row.value)}
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className={cn(
                    "shrink-0 text-[10px]",
                    DECISION_CLASS[decision] ?? DECISION_CLASS.blocked,
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {decision}
                </Badge>
              </div>
              <div className="mt-1.5 grid gap-1.5 text-[11px] sm:grid-cols-2">
                <Info label="reason" value={row.reason} />
                <Info label="source" value={row.source} />
                <Info label="writer" value={row.writer} />
                <Info label="evidence" value={row.evidence_refs ?? []} />
                <Info label="confidence" value={row.confidence} />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Info({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border bg-muted/20 px-2 py-1">
      <div className="font-mono text-[10px] text-muted-foreground">{label}</div>
      <div className="break-words">{formatValue(value, 70)}</div>
    </div>
  );
}

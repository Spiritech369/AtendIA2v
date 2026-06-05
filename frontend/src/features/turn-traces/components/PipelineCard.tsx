import { GitBranch } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  asRecord,
  formatValue,
  type UniversalTraceRecord,
} from "@/features/turn-traces/lib/universalTrace";
import { PanelHeading } from "./DecisionTimeline";

export function PipelineCard({ trace }: { trace: UniversalTraceRecord }) {
  const lifecycle = asRecord(trace.lifecycle);
  const stageBefore = lifecycle?.stage_before ?? null;
  const stageProposed = lifecycle?.stage_proposed ?? null;
  const stageAfter = lifecycle?.stage_after ?? null;
  const statusBefore = lifecycle?.status_before ?? null;
  const statusProposed = lifecycle?.status_proposed ?? null;
  const statusAfter = lifecycle?.status_after ?? null;
  const changed = Boolean(stageAfter || statusAfter);

  return (
    <section className="space-y-2" aria-label="Pipeline card">
      <PanelHeading title="Pipeline" badge={changed ? "validated" : "sin cambio"} />
      <div className="rounded-md border bg-card p-2 text-xs">
        <div className="flex items-center gap-1.5 font-medium">
          <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
          {changed ? "Cambio de etapa validado" : "sin cambio de etapa"}
        </div>
        <div className="mt-2 grid gap-1.5 sm:grid-cols-3">
          <Info label="stage actual" value={stageBefore} />
          <Info label="stage propuesto" value={stageProposed} />
          <Info label="stage validado" value={stageAfter} />
          <Info label="status actual" value={statusBefore} />
          <Info label="status propuesto" value={statusProposed} />
          <Info label="status validado" value={statusAfter} />
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge variant="outline" className="text-[10px]">
            transition {changed ? "allowed" : "none"}
          </Badge>
          {lifecycle?.reason != null && lifecycle.reason !== "" && (
            <Badge variant="outline" className="text-[10px]">
              {formatValue(lifecycle.reason)}
            </Badge>
          )}
        </div>
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

import { CircleAlert, Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  asRecordArray,
  formatValue,
  type UniversalTraceRecord,
} from "@/features/turn-traces/lib/universalTrace";
import { cn } from "@/lib/utils";
import { PanelHeading } from "./DecisionTimeline";

const STATUS_CLASS: Record<string, string> = {
  succeeded: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  executed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  missing: "border-amber-500/40 bg-amber-500/10 text-amber-700",
  skipped: "border-slate-500/40 bg-slate-500/10 text-slate-700",
  failed: "border-rose-500/40 bg-rose-500/10 text-rose-700",
  blocked: "border-red-500/40 bg-red-500/10 text-red-700",
};

export function ToolCards({ trace }: { trace: UniversalTraceRecord }) {
  const decisions = asRecordArray(trace.mandatory_tool_decisions);
  const results = asRecordArray(trace.tool_results);
  const rows = mergeToolRows(decisions, results);

  if (rows.length === 0) {
    return (
      <section className="space-y-2">
        <PanelHeading title="Tools" />
        <div className="text-xs text-muted-foreground">Sin tools obligatorias ni resultados.</div>
      </section>
    );
  }

  return (
    <section className="space-y-2" aria-label="Tool cards">
      <PanelHeading title="Tools" badge={`${rows.length}`} />
      <div className="space-y-1.5">
        {rows.map((row) => (
          <div key={row.key} className="rounded-md border bg-card p-2 text-xs">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 font-mono font-medium">
                  <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
                  {row.toolId}
                </div>
                {row.reason && (
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    Motivo: {row.reason}
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                {row.required && (
                  <Badge variant="outline" className="text-[10px]">
                    obligatoria
                  </Badge>
                )}
                <Badge
                  variant="outline"
                  className={cn("text-[10px]", STATUS_CLASS[row.status] ?? STATUS_CLASS.skipped)}
                >
                  {row.status}
                </Badge>
              </div>
            </div>

            <div className="mt-2 grid gap-1.5 text-[11px] sm:grid-cols-2">
              <Info label="tenant" value={row.tenantId} />
              <Info label="used_for" value={row.usedFor.join(", ") || "sin uso declarado"} />
              <Info label="safe_inputs" value={formatValue(row.safeInputs)} />
              <Info label="citations" value={formatValue(row.citations)} />
            </div>
            <details className="mt-1.5 rounded border bg-muted/20">
              <summary className="cursor-pointer px-2 py-1 text-[11px] text-muted-foreground">
                output estructurado
              </summary>
              <pre className="max-h-40 overflow-auto border-t p-2 text-[10px]">
                {JSON.stringify(row.structuredOutput, null, 2)}
              </pre>
            </details>
            {row.error && (
              <div className="mt-1.5 flex items-center gap-1 text-[11px] text-rose-700">
                <CircleAlert className="h-3 w-3" />
                {row.error}
              </div>
            )}
          </div>
        ))}
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

function mergeToolRows(
  decisions: Array<Record<string, unknown>>,
  results: Array<Record<string, unknown>>,
) {
  const keys = new Set<string>();
  for (const decision of decisions) keys.add(String(decision.tool_id ?? decision.toolId ?? ""));
  for (const result of results) keys.add(String(result.tool_id ?? result.toolId ?? ""));

  return Array.from(keys)
    .filter(Boolean)
    .map((toolId) => {
      const decision = decisions.find(
        (item) => String(item.tool_id ?? item.toolId ?? "") === toolId,
      );
      const result = results.find((item) => String(item.tool_id ?? item.toolId ?? "") === toolId);
      return {
        key: toolId,
        toolId,
        required: Boolean(decision?.required || decision),
        reason: formatOptional(decision?.reason),
        status: String(result?.status ?? decision?.status ?? "missing"),
        tenantId: result?.tenant_id ?? decision?.tenant_id ?? null,
        safeInputs: result?.safe_inputs ?? {},
        structuredOutput: result?.structured_output ?? {},
        citations: result?.citations ?? [],
        usedFor: Array.isArray(result?.used_for)
          ? result.used_for.map(String)
          : blockingScopes(decision),
        error: formatOptional(result?.error ?? decision?.error),
      };
    });
}

function blockingScopes(decision: Record<string, unknown> | undefined): string[] {
  return Array.isArray(decision?.blocking_scopes) ? decision.blocking_scopes.map(String) : [];
}

function formatOptional(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

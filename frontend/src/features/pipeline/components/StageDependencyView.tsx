/**
 * P6 — dependency view inside the stage editor.
 *
 * The /tenants/pipeline/impacted-references/:stage_id endpoint already
 * existed; it powers the impact-aware StageDeleteDialog. P6 surfaces the
 * SAME data INSIDE the stage editor so an operator sees how many
 * conversations currently sit in the stage and which workflows
 * reference it BEFORE changing behavior_mode / rules — not only at the
 * moment of deletion.
 *
 * Read-only and purely informational: no actions, no confirm. It reuses
 * tenantsApi.getStageImpact (the exact method StageDeleteDialog uses —
 * no API-client duplication) and a useQuery keyed on the stage id, so
 * opening the delete dialog right after reads from the same cache.
 *
 * Rendering mirrors StageDeleteDialog's impact block (amber-tinted card
 * + active/inactive workflow badges) so the two surfaces feel like one
 * feature, and collapses to a one-line "Sin dependencias" when zero.
 */
import { useQuery } from "@tanstack/react-query";
import { Link2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { tenantsApi } from "@/features/config/api";
import { cn } from "@/lib/utils";

export function StageDependencyView({ stageId }: { stageId: string }) {
  const impactQuery = useQuery({
    // Same query key family as StageDeleteDialog so both surfaces share
    // one cache entry per stage.
    queryKey: ["pipeline", "impact", stageId],
    queryFn: () => tenantsApi.getStageImpact(stageId),
    enabled: stageId.length > 0,
    // Impact is a snapshot, not realtime — no refetch on focus etc.
    staleTime: 60_000,
  });

  const impact = impactQuery.data;
  const hasImpact =
    impact !== undefined &&
    (impact.conversation_count > 0 || impact.workflow_references.length > 0);

  return (
    <section className="mt-4 border-t pt-3" data-field="stage-dependencies">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
        <Link2 className="size-3.5" />
        Dependencias
      </div>

      {impactQuery.isLoading && (
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      )}

      {impact && !hasImpact && (
        <p className="text-xs text-muted-foreground">
          Sin dependencias — ninguna conversación está en esta etapa y ningún workflow la
          referencia.
        </p>
      )}

      {impact && hasImpact && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
          <p className="mb-2 text-[11px] text-muted-foreground">
            Cambiar el comportamiento o las reglas de esta etapa afecta a:
          </p>
          <ul className="space-y-1 text-xs">
            {impact.conversation_count > 0 && (
              <li>
                <span className="font-medium">{impact.conversation_count}</span> conversación
                {impact.conversation_count === 1 ? "" : "es"} en esta etapa.
              </li>
            )}
            {impact.workflow_references.length > 0 && (
              <li className="space-y-1">
                <div>
                  <span className="font-medium">{impact.workflow_references.length}</span>{" "}
                  workflow(s) referencian esta{" "}
                  <code className="rounded bg-muted px-1 text-[10px]">etapa</code>:
                </div>
                <ul className="ml-4 space-y-0.5 text-[11px]">
                  {impact.workflow_references.map((ref) => (
                    <li
                      // A workflow can reference the same stage in more
                      // than one place (e.g. trigger `from` AND `to`, or
                      // several move_stage nodes), so workflow_id alone
                      // isn't unique — reference_kind + detail pins the
                      // specific reference without an array index.
                      key={`${ref.workflow_id}-${ref.reference_kind}-${ref.detail}`}
                      className="flex items-center gap-1.5"
                    >
                      <Badge
                        variant="outline"
                        className={cn(
                          "px-1.5 py-0 text-[10px]",
                          ref.active
                            ? "border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
                            : "text-muted-foreground",
                        )}
                      >
                        {ref.active ? "activo" : "inactivo"}
                      </Badge>
                      <span className="font-medium">{ref.name}</span>
                      <span className="text-muted-foreground">
                        ({ref.reference_kind === "trigger" ? "trigger" : "move_stage"} ·{" "}
                        {ref.detail})
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            )}
          </ul>
        </div>
      )}
    </section>
  );
}

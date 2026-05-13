/**
 * M5 of the pipeline-automation editor plan.
 *
 * Replaces the lightweight per-stage delete dialog with an impact-aware
 * version. Fetches /tenants/pipeline/impacted-references/:stage_id and
 * surfaces:
 *
 *   - How many conversations currently sit in this stage (they'll be
 *     orphaned until moved).
 *   - Which workflows reference this stage_id (trigger or move_stage
 *     node). Active workflows would silently break on the next event.
 *
 * When the impact is non-zero (conversations > 0 or workflow refs
 * present), we require type-to-confirm: the operator must type the
 * literal stage_id before the destructive button enables. This matches
 * the spec's "type-to-confirm" safety class.
 *
 * When the impact is empty, a plain confirm button is enough — typing
 * the stage_id with no downstream consequences is friction without
 * payoff.
 */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { tenantsApi } from "@/features/config/api";
import { cn } from "@/lib/utils";

interface StageMinimal {
  id: string;
  label: string;
}

export function StageDeleteDialog({
  stage,
  onCancel,
  onConfirm,
}: {
  stage: StageMinimal | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const open = stage !== null;
  const stageId = stage?.id ?? "";

  const impactQuery = useQuery({
    queryKey: ["pipeline", "impact", stageId],
    queryFn: () => tenantsApi.getStageImpact(stageId),
    // Only run when the dialog is actually open. Without a stage_id the
    // API call has no useful target.
    enabled: open && stageId.length > 0,
    // Impact is a snapshot, not realtime — no refetch on focus etc.
    staleTime: 60_000,
  });

  // Confirmation buffer for type-to-confirm. Cleared every time we open
  // the dialog with a new stage.
  const [typed, setTyped] = useState("");
  // useEffect-free reset: when the stage id changes, derive a key from
  // it so React remounts the Input. We don't need useEffect because the
  // key prop is the trigger.

  const impact = impactQuery.data;
  const hasImpact =
    impact !== undefined &&
    (impact.conversation_count > 0 ||
      impact.workflow_references.length > 0);

  // When impact is non-empty we require type-to-confirm. When impact is
  // empty (or hasn't loaded yet), a plain button is fine.
  const confirmEnabled = hasImpact ? typed === stageId : impact !== undefined;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setTyped("");
          onCancel();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            ¿Eliminar la etapa{" "}
            <span className="font-mono text-sm">{stageId}</span>?
          </DialogTitle>
          <DialogDescription>
            El cambio se aplica al pulsar{" "}
            <span className="font-medium">Guardar</span> en el editor. Mientras
            tanto, la etapa permanece visible en el draft.
          </DialogDescription>
        </DialogHeader>

        {/* Impact summary. Loading state on first open, then the real
            counts once /impacted-references returns. */}
        <div className="space-y-2">
          {impactQuery.isLoading && (
            <div className="space-y-1.5">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          )}

          {impact && !hasImpact && (
            <p className="text-xs text-muted-foreground">
              Sin conversaciones ni workflows que referencien esta etapa —
              eliminarla es seguro.
            </p>
          )}

          {impact && hasImpact && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-amber-700 dark:text-amber-300">
                <AlertTriangle className="size-3.5" />
                Impacto al eliminar
              </div>
              <ul className="space-y-1 text-xs">
                {impact.conversation_count > 0 && (
                  <li>
                    <span className="font-medium">
                      {impact.conversation_count}
                    </span>{" "}
                    conversación{impact.conversation_count === 1 ? "" : "es"}{" "}
                    quedarán como huérfanas hasta moverlas a otra etapa.
                  </li>
                )}
                {impact.workflow_references.length > 0 && (
                  <li className="space-y-1">
                    <div>
                      <span className="font-medium">
                        {impact.workflow_references.length}
                      </span>{" "}
                      workflow(s) referencian este{" "}
                      <code className="rounded bg-muted px-1 text-[10px]">
                        stage_id
                      </code>{" "}
                      y dejarán de funcionar:
                    </div>
                    <ul className="ml-4 space-y-0.5 text-[11px]">
                      {impact.workflow_references.map((ref, i) => (
                        <li
                          key={`${ref.workflow_id}-${i}`}
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
                            ({ref.reference_kind === "trigger" ? "trigger" : "move_stage"} · {ref.detail})
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                )}
              </ul>
            </div>
          )}

          {/* Type-to-confirm only when impact is non-empty. */}
          {hasImpact && (
            <div className="space-y-1.5">
              <Label className="text-[11px]">
                Escribe{" "}
                <code className="rounded bg-muted px-1 font-mono text-[10px]">
                  {stageId}
                </code>{" "}
                para confirmar:
              </Label>
              <Input
                key={stageId} /* remount per stage so buffer clears */
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                className="h-8 font-mono text-xs"
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              setTyped("");
              onCancel();
            }}
          >
            Cancelar
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              setTyped("");
              onConfirm();
            }}
            disabled={!confirmEnabled}
            title={
              !confirmEnabled && hasImpact
                ? `Escribe "${stageId}" para confirmar`
                : undefined
            }
          >
            <Trash2 className="mr-1.5 size-3.5" />
            Eliminar etapa
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

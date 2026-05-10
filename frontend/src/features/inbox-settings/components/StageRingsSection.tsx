import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { tenantsApi } from "@/features/config/api";
import type { InboxConfig, StageRing } from "../types";

interface Props {
  draft: InboxConfig;
  patchDraft: (patch: Partial<InboxConfig>) => void;
  canEdit: boolean;
}

interface PipelineStage {
  id: string;
  label: string;
}

export function StageRingsSection({ draft, patchDraft, canEdit }: Props) {
  const pipelineQuery = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });

  const rings = draft.stage_rings;

  const update = (stageId: string, patch: Partial<StageRing>) => {
    const existing = rings.find((r) => r.stage_id === stageId);
    if (existing) {
      patchDraft({
        stage_rings: rings.map((r) => (r.stage_id === stageId ? { ...r, ...patch } : r)),
      });
    } else {
      patchDraft({
        stage_rings: [
          ...rings,
          { stage_id: stageId, emoji: "⚪", color: "#6b7280", sla_hours: null, ...patch },
        ],
      });
    }
  };

  if (pipelineQuery.isLoading) return <Skeleton className="h-64 w-full" />;

  const def = pipelineQuery.data?.definition as { stages?: PipelineStage[] } | undefined;
  const pipelineStages: PipelineStage[] = def?.stages ?? [];

  type MergedRing = StageRing & { label: string };

  const mergedRings: MergedRing[] = pipelineStages.map((s) => {
    const ring = rings.find((r) => r.stage_id === s.id) ?? {
      stage_id: s.id,
      emoji: "⚪",
      color: "#6b7280",
      sla_hours: null,
    };
    return { ...ring, label: s.label };
  });

  // Orphans: rings with overrides but no matching pipeline stage
  const orphans: MergedRing[] = rings
    .filter((r) => !pipelineStages.find((s) => s.id === r.stage_id))
    .map((r) => ({ ...r, label: r.stage_id }));

  const all = [...mergedRings, ...orphans];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Anillos de etapa</CardTitle>
          <p className="text-xs text-muted-foreground">
            El borde del avatar en cada fila indica la etapa del cliente. Las etapas vienen del
            pipeline activo.
          </p>
        </CardHeader>
        <CardContent>
          {pipelineQuery.isError && (
            <div className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
              No hay pipeline activo. Crea uno en{" "}
              <strong>Configuración → Pipeline</strong> para gestionar los anillos.
            </div>
          )}

          {all.length === 0 ? (
            <p className="text-center text-xs text-muted-foreground py-8">
              Sin etapas. Crea un pipeline primero.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {all.map((ring) => (
                <div
                  key={ring.stage_id}
                  className="flex items-center gap-2 rounded-lg border bg-card p-2.5"
                >
                  {/* Avatar preview */}
                  <div className="relative h-8 w-8 shrink-0">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-sm">
                      {ring.emoji}
                    </div>
                    <div
                      className="pointer-events-none absolute inset-0 rounded-full border-2"
                      style={{ borderColor: ring.color }}
                    />
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{ring.label}</p>
                    <p className="font-mono text-[9px] text-muted-foreground">{ring.stage_id}</p>
                  </div>

                  {/* Emoji */}
                  <Input
                    value={ring.emoji}
                    onChange={(e) => update(ring.stage_id, { emoji: e.target.value })}
                    disabled={!canEdit}
                    className="h-7 w-10 p-1 text-center text-sm"
                    maxLength={2}
                    title="Emoji de etapa"
                  />

                  {/* Color picker */}
                  <div className="relative h-7 w-7 shrink-0">
                    <div
                      className="h-7 w-7 rounded border border-border/50"
                      style={{ background: ring.color }}
                    />
                    {canEdit && (
                      <input
                        type="color"
                        value={ring.color}
                        onChange={(e) => update(ring.stage_id, { color: e.target.value })}
                        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                        title="Color del anillo"
                      />
                    )}
                  </div>

                  {/* SLA */}
                  <Input
                    type="number"
                    min={0}
                    max={720}
                    placeholder="∞"
                    value={ring.sla_hours ?? ""}
                    onChange={(e) =>
                      update(ring.stage_id, {
                        sla_hours: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                    disabled={!canEdit}
                    className="h-7 w-14 font-mono text-xs"
                    title="SLA en horas (0 = sin límite)"
                  />
                  <span className="shrink-0 text-[9px] text-muted-foreground">h</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

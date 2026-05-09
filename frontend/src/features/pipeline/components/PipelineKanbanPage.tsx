import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Bell, Inbox, Settings, Timer, User } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { conversationsApi } from "@/features/conversations/api";
import { pipelineApi, type PipelineConversationCard, type StageGroup } from "@/features/pipeline/api";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

function formatRelative(iso: string): string {
  const dt = new Date(iso);
  const diffMs = Date.now() - dt.getTime();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "ahora";
  if (diffMin < 60) return `hace ${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `hace ${diffH}h`;
  const diffD = Math.round(diffH / 24);
  return `hace ${diffD}d`;
}

export function PipelineKanbanPage() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<"all" | "mine">("all");
  const board = useQuery({
    queryKey: ["pipeline", "board", scope],
    queryFn: () =>
      pipelineApi.board(
        scope === "mine" && user?.id ? { assigned_user_id: user.id } : {},
      ),
  });
  const alerts = useQuery({ queryKey: ["pipeline", "alerts"], queryFn: pipelineApi.alerts });
  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) =>
      conversationsApi.patchConversation(id, { current_stage: stage }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
  });

  // ── Loading / error / empty pipeline ─────────────────────────────
  if (board.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-72" />
        <div className="flex gap-4 overflow-x-auto pb-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-96 w-80 shrink-0" />
          ))}
        </div>
      </div>
    );
  }

  if (board.isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 p-6">
          <div className="flex items-center gap-2 text-base font-medium">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            Sin pipeline activo
          </div>
          <p className="text-sm text-muted-foreground">
            Este tenant no tiene una versión de pipeline activa todavía.
            Crea las etapas en Configuración → Pipeline para empezar a usar
            el tablero.
          </p>
          <Button asChild>
            <Link to="/config">
              <Settings className="mr-2 h-4 w-4" /> Ir a Configuración
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  const stages = board.data?.stages ?? [];
  // Only "real" stages (not the synthetic orphan group) feed the move-to
  // dropdown — operators rescue an orphan by sending it INTO an active
  // stage, never by moving things INTO the orphan group.
  const realStages = stages.filter((s) => !s.is_orphan);
  const orphanGroup = stages.find((s) => s.is_orphan);

  // Aggregate metrics across all real stages.
  const totalConversations = realStages.reduce((sum, s) => sum + s.total_count, 0);
  const staleCount = alerts.data?.items.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Pipeline de ventas</h1>
          <p className="text-sm text-muted-foreground">
            {totalConversations} conversación(es) en {realStages.length} etapa(s)
            {scope === "mine" && " · filtrado: solo mías"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={scope === "mine" ? "default" : "outline"}
            size="sm"
            onClick={() => setScope(scope === "mine" ? "all" : "mine")}
            disabled={!user?.id}
          >
            <User className="mr-2 h-4 w-4" />
            {scope === "mine" ? "Solo mías" : "Todas"}
          </Button>
          <Badge
            variant={staleCount > 0 ? "destructive" : "secondary"}
            className="gap-1"
          >
            <Bell className="h-3 w-3" /> {staleCount} {staleCount === 1 ? "alerta" : "alertas"}
          </Badge>
          <Button variant="outline" asChild>
            <Link to="/config">
              <Settings className="mr-2 h-4 w-4" /> Configurar etapas
            </Link>
          </Button>
        </div>
      </div>

      {/* Aggregate metric cards across stages */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricTile label="Total" value={totalConversations} />
        {realStages.slice(0, 3).map((s) => (
          <MetricTile key={s.stage_id} label={s.stage_label} value={s.total_count} />
        ))}
      </div>

      {orphanGroup && orphanGroup.total_count > 0 && (
        <div
          className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="space-y-1">
            <div className="font-medium">
              {orphanGroup.total_count} conversación(es) en una etapa que ya
              no existe en el pipeline activo.
            </div>
            <div className="text-xs text-amber-800 dark:text-amber-300">
              Probablemente la etapa fue renombrada o eliminada en
              Configuración. Usa el selector de cada tarjeta para
              moverlas a una etapa válida — sin esto, no aparecerían en
              ninguna columna.
            </div>
          </div>
        </div>
      )}

      <div className="flex gap-4 overflow-x-auto pb-2">
        {stages.length === 0 ? (
          <Card className="w-full">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Inbox className="h-8 w-8 text-muted-foreground" />
              <div className="text-sm font-medium">
                El pipeline activo no tiene etapas
              </div>
              <p className="max-w-md text-xs text-muted-foreground">
                Define al menos una etapa en Configuración → Pipeline para
                que las conversaciones puedan agruparse aquí.
              </p>
              <Button size="sm" asChild>
                <Link to="/config">
                  <Settings className="mr-2 h-3 w-3" /> Crear etapas
                </Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          stages.map((stage) => (
            <StageColumn
              key={stage.stage_id}
              stage={stage}
              stages={realStages}
              onMove={(id, next) => move.mutate({ id, stage: next })}
            />
          ))
        )}
      </div>
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="py-3">
        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
      </CardContent>
    </Card>
  );
}

function StageColumn({
  stage,
  stages,
  onMove,
}: {
  stage: StageGroup;
  stages: StageGroup[];
  onMove: (id: string, stage: string) => void;
}) {
  const truncated = stage.total_count > stage.conversations.length;
  return (
    <Card
      className={cn(
        "w-80 shrink-0 max-h-[calc(100vh-280px)] flex flex-col",
        stage.is_orphan && "border-amber-300 bg-amber-50/50 dark:bg-amber-950/10",
      )}
    >
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-1.5">
            {stage.is_orphan ? (
              <AlertTriangle className="h-3.5 w-3.5 text-amber-700" />
            ) : (
              <span
                className={cn(
                  "inline-block h-2 w-2 rounded-full",
                  stage.total_count > 0 ? "bg-emerald-500" : "bg-muted-foreground/40",
                )}
              />
            )}
            {stage.stage_label}
          </span>
          <Badge variant="outline" className="tabular-nums">
            {stage.total_count}
          </Badge>
        </CardTitle>
        {stage.timeout_hours !== null && stage.timeout_hours > 0 && (
          <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <Timer className="h-2.5 w-2.5" /> alerta tras {stage.timeout_hours}h sin actividad
          </div>
        )}
      </CardHeader>
      <CardContent className="flex-1 space-y-2 overflow-y-auto">
        {stage.conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-1 rounded-md border border-dashed py-6 text-center">
            <Inbox className="h-4 w-4 text-muted-foreground" />
            <span className="text-[11px] text-muted-foreground">
              {stage.is_orphan
                ? "(no quedan tarjetas huérfanas)"
                : "Sin conversaciones en esta etapa"}
            </span>
          </div>
        ) : (
          stage.conversations.map((card) => (
            <ConversationCard
              key={card.id}
              card={card}
              stages={stages}
              isOrphan={stage.is_orphan ?? false}
              onMove={onMove}
            />
          ))
        )}
        {truncated && (
          <div className="rounded-md border border-dashed bg-muted/30 p-2 text-center text-[11px] text-muted-foreground">
            Mostrando {stage.conversations.length} de {stage.total_count}.
            Filtra desde la lista de Conversaciones para ver el resto.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ConversationCard({
  card,
  stages,
  isOrphan,
  onMove,
}: {
  card: PipelineConversationCard;
  stages: StageGroup[];
  isOrphan: boolean;
  onMove: (id: string, stage: string) => void;
}) {
  // For orphan cards the ``Select`` ``value`` is the (now-invalid) stale stage
  // id; the dropdown options are real stages. We render the stale value as a
  // placeholder so the operator sees what to rescue.
  return (
    <div
      className={cn(
        "space-y-2 rounded-md border bg-card p-3 text-sm shadow-sm transition-colors hover:border-foreground/20",
        isOrphan && "border-amber-300",
        card.is_stale && !isOrphan && "border-destructive/30",
      )}
    >
      <Link
        to="/conversations/$conversationId"
        params={{ conversationId: card.id }}
        className="block"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">
              {card.customer_name ?? card.customer_phone}
            </div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">
              {card.customer_phone}
            </div>
          </div>
          {card.is_stale && (
            <Badge variant="destructive" className="shrink-0 gap-1">
              <Bell className="h-2.5 w-2.5" /> Alerta
            </Badge>
          )}
        </div>
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          {card.last_message_text ?? "Sin mensajes"}
        </p>
        <div className="mt-2 flex items-center gap-1 text-[10px] text-muted-foreground">
          <Timer className="h-2.5 w-2.5" />
          {formatRelative(card.last_activity_at)}
        </div>
        {isOrphan && (
          <p className="mt-1 text-[11px] text-amber-800 dark:text-amber-300">
            Etapa actual <code>{card.current_stage}</code> ya no existe.
          </p>
        )}
      </Link>
      <Select
        value={isOrphan ? undefined : card.current_stage}
        onValueChange={(stage) => onMove(card.id, stage)}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder={isOrphan ? "Mover a etapa válida…" : undefined} />
        </SelectTrigger>
        <SelectContent>
          {stages.map((stage) => (
            <SelectItem key={stage.stage_id} value={stage.stage_id}>
              Mover → {stage.stage_label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

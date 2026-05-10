import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  Archive,
  Bell,
  ChevronDown,
  Clock,
  GripVertical,
  Inbox,
  MoreHorizontal,
  Move,
  Plus,
  Settings,
  Timer,
  User,
  UserX,
  X,
} from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineEditor } from "@/features/config/components/PipelineEditor";
import { conversationsApi } from "@/features/conversations/api";
import { pipelineApi, type PipelineConversationCard, type StageGroup } from "@/features/pipeline/api";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "ahora";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  return `${Math.round(diffH / 24)}d`;
}

function initials(name: string | null, fallback: string): string {
  if (!name) return fallback.slice(0, 2).toUpperCase();
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

type KpiFilter = "stale" | "inactive_24h" | "unassigned" | "orphan" | null;

const STAGE_COLORS: Record<string, string> = {
  nuevo: "#6366f1",
  nuevo_lead: "#6366f1",
  en_conversacion: "#3b82f6",
  stage_chat: "#3b82f6",
  propuesta: "#f59e0b",
  stage_propuesta: "#f59e0b",
  negociacion: "#8b5cf6",
  stage_negociacion: "#8b5cf6",
  cerrado_ganado: "#10b981",
  stage_won: "#10b981",
  cerrado_perdido: "#ef4444",
  stage_lost: "#ef4444",
};

function stageColor(stageId: string, definitionColor?: string): string {
  if (definitionColor) return definitionColor;
  return STAGE_COLORS[stageId] ?? "#6b7280";
}

// ── KPI Tile ─────────────────────────────────────────────────────────────────

interface KpiTileProps {
  icon: typeof Bell;
  iconColor: string;
  bgColor: string;
  label: string;
  value: number;
  filter: KpiFilter;
  active: boolean;
  onToggle: (f: KpiFilter) => void;
}

function KpiTile({ icon: Icon, iconColor, bgColor, label, value, filter, active, onToggle }: KpiTileProps) {
  return (
    <button
      type="button"
      onClick={() => onToggle(active ? null : filter)}
      className={cn(
        "group flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-all hover:shadow-sm",
        active
          ? "border-primary/40 bg-primary/5 shadow-sm"
          : "border-border bg-card hover:border-border/80",
      )}
      title={`Filtrar por: ${label}`}
    >
      <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-md", bgColor)}>
        <Icon className={cn("size-4", iconColor)} />
      </div>
      <div className="min-w-0">
        <p className="text-xl font-semibold tabular-nums leading-none">{value}</p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{label}</p>
      </div>
      {active && (
        <div className="ml-auto shrink-0">
          <X className="size-3.5 text-muted-foreground" />
        </div>
      )}
    </button>
  );
}

// ── Stage Column ──────────────────────────────────────────────────────────────

function StageColumn({
  stage,
  allRealStages,
  stageColors,
  dragState,
  kpiFilter,
  onDragOver,
  onDragLeave,
  onDrop,
  onMove,
  onArchive,
  onRescueAll,
}: {
  stage: StageGroup;
  allRealStages: StageGroup[];
  stageColors: Record<string, string>;
  dragState: { cardId: string; fromStage: string } | null;
  kpiFilter: KpiFilter;
  onDragOver: (e: React.DragEvent, stageId: string) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent, stageId: string) => void;
  onMove: (id: string, toStage: string) => void;
  onArchive: (id: string) => void;
  onRescueAll: (toStage: string) => void;
}) {
  const [dropHover, setDropHover] = useState(false);
  const [rescueTarget, setRescueTarget] = useState<string>("");
  const color = stageColors[stage.stage_id] ?? "#6b7280";
  const isBeingDraggedOver = dragState !== null && dragState.fromStage !== stage.stage_id && dropHover;
  const bottleneck = !stage.is_orphan && stage.total_count >= 10;

  const visibleCards = useMemo(() => {
    let cards = stage.conversations;
    const now = Date.now();
    if (kpiFilter === "stale") cards = cards.filter((c) => c.is_stale);
    if (kpiFilter === "inactive_24h")
      cards = cards.filter((c) => now - new Date(c.last_activity_at).getTime() > 24 * 3600_000);
    return cards;
  }, [stage.conversations, kpiFilter]);

  return (
    <div
      className={cn(
        "flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border transition-all",
        stage.is_orphan
          ? "border-destructive/40 bg-destructive/5"
          : isBeingDraggedOver
            ? "border-primary ring-1 ring-primary/30"
            : "border-border bg-card",
      )}
      onDragOver={(e) => {
        if (stage.is_orphan) return;
        setDropHover(true);
        onDragOver(e, stage.stage_id);
      }}
      onDragLeave={() => {
        setDropHover(false);
        onDragLeave();
      }}
      onDrop={(e) => {
        setDropHover(false);
        if (!stage.is_orphan) onDrop(e, stage.stage_id);
      }}
    >
      {/* Column header */}
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2.5">
        {stage.is_orphan ? (
          <AlertTriangle className="size-3.5 shrink-0 text-destructive" />
        ) : (
          <span
            className="size-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: color }}
          />
        )}
        <span className="flex-1 truncate text-sm font-semibold">{stage.stage_label}</span>
        <Badge
          variant={stage.is_orphan ? "destructive" : "outline"}
          className="shrink-0 tabular-nums text-[10px]"
        >
          {stage.total_count}
        </Badge>
        {!stage.is_orphan && (
          <Button
            variant="ghost"
            size="icon"
            className="size-6 shrink-0 opacity-60 hover:opacity-100"
            title="Agregar conversación a esta etapa"
          >
            <Plus className="size-3.5" />
          </Button>
        )}
      </div>

      {/* Bottleneck + timeout info */}
      {(bottleneck || stage.timeout_hours) && !stage.is_orphan && (
        <div className="flex items-center gap-2 border-b bg-amber-500/5 px-3 py-1.5">
          {bottleneck && (
            <Badge className="h-5 gap-1 bg-amber-500/20 px-1.5 text-[9px] text-amber-700 dark:text-amber-300 hover:bg-amber-500/20">
              <AlertTriangle className="size-2.5" /> Cuello de botella
            </Badge>
          )}
          {stage.timeout_hours !== null && stage.timeout_hours > 0 && (
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <Timer className="size-2.5" /> alerta tras {stage.timeout_hours}h
            </span>
          )}
        </div>
      )}

      {/* Drop target overlay */}
      {isBeingDraggedOver && (
        <div className="mx-2 mt-2 flex items-center justify-center rounded-lg border-2 border-dashed border-primary/60 bg-primary/5 py-4 text-xs font-medium text-primary">
          Suelta aquí para mover a {stage.stage_label}
        </div>
      )}

      {/* Card list */}
      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {visibleCards.length === 0 ? (
          <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed py-8 text-center">
            <Inbox className="size-4 text-muted-foreground/50" />
            <span className="text-[11px] text-muted-foreground">
              {stage.is_orphan
                ? "No hay tarjetas huérfanas"
                : kpiFilter
                  ? "Sin coincidencias con el filtro"
                  : "Sin conversaciones"}
            </span>
          </div>
        ) : (
          visibleCards.map((card) => (
            <KanbanCard
              key={card.id}
              card={card}
              isOrphan={stage.is_orphan ?? false}
              allRealStages={allRealStages}
              onMove={onMove}
              onArchive={onArchive}
            />
          ))
        )}

        {stage.total_count > stage.conversations.length && (
          <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-center text-[11px] text-muted-foreground">
            Mostrando {stage.conversations.length} de {stage.total_count}. Ve a Conversaciones para ver el resto.
          </div>
        )}
      </div>

      {/* Orphan rescue footer */}
      {stage.is_orphan && stage.total_count > 0 && (
        <div className="shrink-0 border-t p-3">
          <p className="mb-2 text-[10px] text-muted-foreground">
            Selecciona un destino para mover estas conversaciones.
          </p>
          <div className="flex gap-1.5">
            <select
              value={rescueTarget}
              onChange={(e) => setRescueTarget(e.target.value)}
              className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              aria-label="Seleccionar etapa destino para rescatar"
            >
              <option value="">— Destino —</option>
              {allRealStages.map((s) => (
                <option key={s.stage_id} value={s.stage_id}>
                  {s.stage_label}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="destructive"
              className="h-7 shrink-0 px-2 text-xs"
              disabled={!rescueTarget}
              onClick={() => {
                if (rescueTarget) onRescueAll(rescueTarget);
              }}
            >
              + Rescatar todos ({stage.total_count})
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Kanban Card ───────────────────────────────────────────────────────────────

function KanbanCard({
  card,
  isOrphan,
  allRealStages,
  onMove,
  onArchive,
}: {
  card: PipelineConversationCard;
  isOrphan: boolean;
  allRealStages: StageGroup[];
  onMove: (id: string, toStage: string) => void;
  onArchive: (id: string) => void;
}) {
  const [isDragging, setIsDragging] = useState(false);

  return (
    <div
      draggable={!isOrphan}
      onDragStart={(e) => {
        setIsDragging(true);
        e.dataTransfer.setData("cardId", card.id);
        e.dataTransfer.setData("fromStage", card.current_stage);
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragEnd={() => setIsDragging(false)}
      className={cn(
        "group relative rounded-lg border bg-card p-3 shadow-sm transition-all",
        "hover:border-foreground/20 hover:shadow-md",
        isOrphan && "border-destructive/40",
        card.is_stale && !isOrphan && "border-amber-300/60 dark:border-amber-600/40",
        isDragging && "opacity-40 shadow-lg",
        !isOrphan && "cursor-grab active:cursor-grabbing",
      )}
    >
      {/* Drag handle + overflow menu */}
      <div className="absolute right-2 top-2 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
        <GripVertical className="size-3.5 text-muted-foreground/50" aria-hidden />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-6"
              title="Opciones"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Move className="mr-2 size-3.5" /> Mover
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                {allRealStages
                  .filter((s) => s.stage_id !== card.current_stage)
                  .map((s) => (
                    <DropdownMenuItem key={s.stage_id} onClick={() => onMove(card.id, s.stage_id)}>
                      {s.stage_label}
                    </DropdownMenuItem>
                  ))}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={() => onArchive(card.id)}
            >
              <Archive className="mr-2 size-3.5" /> Archivar
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Customer info */}
      <Link
        to="/conversations/$conversationId"
        params={{ conversationId: card.id }}
        className="block"
        onClick={(e) => isDragging && e.preventDefault()}
      >
        <div className="flex items-start gap-2 pr-12">
          <Avatar className="size-7 shrink-0">
            <AvatarFallback className="text-[10px]">
              {initials(card.customer_name, card.customer_phone)}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold">
              {card.customer_name ?? card.customer_phone}
            </p>
            <p className="truncate font-mono text-[10px] text-muted-foreground">
              {card.customer_phone}
            </p>
          </div>
        </div>

        {card.last_message_text && (
          <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
            {card.last_message_text}
          </p>
        )}

        {isOrphan && (
          <p className="mt-1 text-[10px] text-destructive">
            Etapa <code className="font-mono">{card.current_stage}</code> ya no existe.
          </p>
        )}

        {/* Footer: time + stale badge */}
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
            <Clock className="size-2.5" />
            {formatRelative(card.last_activity_at)}
          </span>
          {card.is_stale && !isOrphan && (
            <Badge
              variant="outline"
              className="h-4 gap-1 border-amber-300 px-1 text-[9px] text-amber-700 dark:border-amber-600 dark:text-amber-300"
            >
              <Bell className="size-2.5" /> Alerta
            </Badge>
          )}
        </div>
      </Link>

      {/* Orphan move-to select */}
      {isOrphan && (
        <select
          className="mt-2 w-full rounded-md border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value) onMove(card.id, e.target.value);
          }}
          onClick={(e) => e.stopPropagation()}
          aria-label="Mover a etapa válida"
        >
          <option value="">Mover a etapa válida…</option>
          {allRealStages.map((s) => (
            <option key={s.stage_id} value={s.stage_id}>
              {s.stage_label}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function PipelineKanbanPage() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [kpiFilter, setKpiFilter] = useState<KpiFilter>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [dragState, setDragState] = useState<{ cardId: string; fromStage: string } | null>(null);

  const board = useQuery({
    queryKey: ["pipeline", "board", scope],
    queryFn: () =>
      pipelineApi.board(scope === "mine" && user?.id ? { assigned_user_id: user.id } : {}),
  });
  const alerts = useQuery({ queryKey: ["pipeline", "alerts"], queryFn: pipelineApi.alerts });

  // Use pipeline definition to get stage colors
  const stageColorMap = useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    for (const s of board.data?.stages ?? []) {
      map[s.stage_id] = stageColor(s.stage_id);
    }
    return map;
  }, [board.data]);

  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) =>
      conversationsApi.patchConversation(id, { current_stage: stage }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => {
      toast.error("Movimiento no válido", {
        description: e.message || "No se pudo mover la conversación a esta etapa.",
      });
    },
  });

  const stages = board.data?.stages ?? [];
  const realStages = stages.filter((s) => !s.is_orphan);
  const orphanGroup = stages.find((s) => s.is_orphan);

  // KPI counts
  const staleCount = alerts.data?.items.length ?? 0;
  const orphanCount = orphanGroup?.total_count ?? 0;
  const inactive24h = useMemo(() => {
    const cutoff = Date.now() - 24 * 3600_000;
    return realStages.flatMap((s) => s.conversations).filter((c) => new Date(c.last_activity_at).getTime() < cutoff).length;
  }, [realStages]);
  const unassignedCount = 0; // API doesn't return this yet

  const handleDragOver = useCallback((e: React.DragEvent, stageId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const handleDragLeave = useCallback(() => {
    // handled per-column
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent, toStage: string) => {
      const cardId = e.dataTransfer.getData("cardId");
      const fromStage = e.dataTransfer.getData("fromStage");
      if (!cardId || fromStage === toStage) return;
      setDragState(null);
      move.mutate({ id: cardId, stage: toStage });
    },
    [move],
  );

  const handleRescueAll = useCallback(
    (toStage: string) => {
      if (!orphanGroup) return;
      for (const card of orphanGroup.conversations) {
        move.mutate({ id: card.id, stage: toStage });
      }
      toast.success(`Rescatando ${orphanGroup.total_count} conversación(es) → ${toStage}`);
    },
    [orphanGroup, move],
  );

  const handleArchive = useCallback(
    (_id: string) => {
      toast("Archivar conversación", {
        description: "Esta acción no está disponible aún desde Pipeline.",
      });
    },
    [],
  );

  // ── Loading ──────────────────────────────────────────────────────────────
  if (board.isLoading) {
    return (
      <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col gap-0 overflow-hidden">
        <div className="grid grid-cols-4 gap-3 border-b p-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
        <div className="flex flex-1 gap-4 overflow-x-auto p-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-full w-72 shrink-0 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (board.isError) {
    return (
      <div className="-m-6 flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <Card>
          <CardContent className="flex flex-col items-start gap-3 p-6">
            <div className="flex items-center gap-2 text-base font-medium">
              <AlertTriangle className="size-5 text-amber-600" />
              Sin pipeline activo
            </div>
            <p className="text-sm text-muted-foreground">
              Este tenant no tiene etapas de pipeline configuradas. Agrégalas en Configuración → Pipeline.
            </p>
            <Button asChild>
              <Link to="/config">
                <Settings className="mr-2 size-4" /> Ir a Configuración
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const totalConversations = realStages.reduce((s, g) => s + g.total_count, 0);

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
      {/* KPI tiles row */}
      <div className="shrink-0 border-b bg-background">
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
          <KpiTile
            icon={Timer}
            iconColor="text-amber-600"
            bgColor="bg-amber-500/10"
            label="Stale"
            value={staleCount}
            filter="stale"
            active={kpiFilter === "stale"}
            onToggle={setKpiFilter}
          />
          <KpiTile
            icon={Clock}
            iconColor="text-orange-600"
            bgColor="bg-orange-500/10"
            label="Sin actividad 24h"
            value={inactive24h}
            filter="inactive_24h"
            active={kpiFilter === "inactive_24h"}
            onToggle={setKpiFilter}
          />
          <KpiTile
            icon={UserX}
            iconColor="text-blue-600"
            bgColor="bg-blue-500/10"
            label="Sin asignar"
            value={unassignedCount}
            filter="unassigned"
            active={kpiFilter === "unassigned"}
            onToggle={setKpiFilter}
          />
          <KpiTile
            icon={AlertTriangle}
            iconColor="text-destructive"
            bgColor="bg-destructive/10"
            label="Huérfanos"
            value={orphanCount}
            filter="orphan"
            active={kpiFilter === "orphan"}
            onToggle={setKpiFilter}
          />
        </div>

        {/* Sub-header: scope toggle + total + settings */}
        <div className="flex items-center justify-between border-t px-4 py-2">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold">Pipeline de ventas</h1>
            <span className="text-xs text-muted-foreground">
              {totalConversations} conversación{totalConversations !== 1 ? "es" : ""} ·{" "}
              {realStages.length} etapa{realStages.length !== 1 ? "s" : ""}
              {scope === "mine" && " · solo mías"}
            </span>
            {kpiFilter && (
              <button
                type="button"
                onClick={() => setKpiFilter(null)}
                className="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary hover:bg-primary/20"
              >
                <X className="size-2.5" /> Limpiar filtro
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={scope === "mine" ? "default" : "outline"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setScope(scope === "mine" ? "all" : "mine")}
              disabled={!user?.id}
            >
              <User className="mr-1.5 size-3" />
              {scope === "mine" ? "Solo mías" : "Todas"}
            </Button>
            <Button
              variant={showEditor ? "secondary" : "outline"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setShowEditor((v) => !v)}
            >
              <Settings className="mr-1.5 size-3" />
              Configurar etapas
            </Button>
          </div>
        </div>
      </div>

      {/* Main area: kanban columns + optional editor panel */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Kanban board */}
        <div className="flex flex-1 gap-4 overflow-x-auto p-4">
          {stages.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
              <Inbox className="size-8 text-muted-foreground/50" />
              <p className="text-sm font-medium">El pipeline no tiene etapas</p>
              <p className="max-w-xs text-xs text-muted-foreground">
                Define etapas en Configuración → Pipeline para que las conversaciones se agrupen aquí.
              </p>
              <Button size="sm" onClick={() => setShowEditor(true)}>
                <Settings className="mr-2 size-3" /> Configurar pipeline
              </Button>
            </div>
          ) : (
            stages.map((stage) => (
              <StageColumn
                key={stage.stage_id}
                stage={stage}
                allRealStages={realStages}
                stageColors={stageColorMap}
                dragState={dragState}
                kpiFilter={kpiFilter === "orphan" && !stage.is_orphan ? null : kpiFilter}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onMove={(id, toStage) => move.mutate({ id, stage: toStage })}
                onArchive={handleArchive}
                onRescueAll={handleRescueAll}
              />
            ))
          )}
        </div>

        {/* Editor panel */}
        {showEditor && (
          <div className="w-80 shrink-0 overflow-hidden border-l bg-background">
            <PipelineEditor onClose={() => setShowEditor(false)} />
          </div>
        )}
      </div>
    </div>
  );
}

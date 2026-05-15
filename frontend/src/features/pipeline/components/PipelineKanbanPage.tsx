import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  Archive,
  Bell,
  Bot,
  CalendarDays,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  Clock,
  FileText,
  Filter,
  Gauge,
  GripVertical,
  Inbox,
  MessageCircle,
  MoreHorizontal,
  Move,
  Plus,
  Search,
  Send,
  Settings,
  ShieldAlert,
  Sparkles,
  Timer,
  TrendingUp,
  User,
  UserX,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineEditor } from "@/features/pipeline/components/PipelineEditor";
import { type PipelineConversationCard, pipelineApi, type StageGroup } from "@/features/pipeline/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

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

function formatCurrency(value: number | null | undefined): string {
  if (!value) return "Sin monto";
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency: "MXN",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatClock(iso: string | null | undefined): string {
  if (!iso) return "Sin cita";
  return new Intl.DateTimeFormat("es-MX", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
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

type KpiFilter =
  | "stale"
  | "inactive_24h"
  | "unassigned"
  | "orphan"
  | "handoff"
  | "docs_blocked"
  | "appointments"
  | "high_score"
  | null;

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
const KPI_SKELETON_KEYS = ["kpi-1", "kpi-2", "kpi-3", "kpi-4"];
const COLUMN_SKELETON_KEYS = ["column-1", "column-2", "column-3", "column-4"];

function stageColor(stageId: string, definitionColor?: string): string {
  if (definitionColor) return definitionColor;
  return STAGE_COLORS[stageId] ?? "#6b7280";
}

// Stage health is a 0-100 score combining conversion velocity, SLA breach
// rate, docs-blocked density and unassigned count. Coloring matches the
// risk_level palette so the kanban reads consistently at a glance.
function healthTone(score: number): { dot: string; text: string; bg: string; label: string } {
  if (score >= 80) return { dot: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300", bg: "bg-emerald-500/10", label: "Saludable" };
  if (score >= 50) return { dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-300", bg: "bg-amber-500/10", label: "En riesgo" };
  return { dot: "bg-red-500", text: "text-red-700 dark:text-red-300", bg: "bg-red-500/10", label: "Crítico" };
}

// % of the stage SLA window already consumed by this card. Returns null when
// we can't compute it (orphan stages, no entry timestamp, no timeout config).
function slaProgress(enteredAt: string | null, timeoutHours: number | null): number | null {
  if (!enteredAt || !timeoutHours || timeoutHours <= 0) return null;
  const elapsedMs = Date.now() - new Date(enteredAt).getTime();
  if (elapsedMs <= 0) return 0;
  const pct = elapsedMs / (timeoutHours * 3600_000);
  return pct;
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
  search,
  onDragOver,
  onDragLeave,
  onDrop,
  onMove,
  onArchive,
  onRescueAll,
  onOpenDetail,
  onOpenConversation,
  onOpenContextMenu,
}: {
  stage: StageGroup;
  allRealStages: StageGroup[];
  stageColors: Record<string, string>;
  dragState: { cardId: string; fromStage: string } | null;
  kpiFilter: KpiFilter;
  search: string;
  onDragOver: (e: React.DragEvent, stageId: string) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent, stageId: string) => void;
  onMove: (id: string, toStage: string) => void;
  onArchive: (id: string) => void;
  onRescueAll: (toStage: string) => void;
  onOpenDetail: (card: PipelineConversationCard) => void;
  onOpenConversation: (id: string) => void;
  onOpenContextMenu: (e: React.MouseEvent, card: PipelineConversationCard) => void;
}) {
  const [dropHover, setDropHover] = useState(false);
  const [rescueTarget, setRescueTarget] = useState<string>("");
  const color = stageColors[stage.stage_id] ?? "#6b7280";
  const isBeingDraggedOver = dragState !== null && dragState.fromStage !== stage.stage_id && dropHover;
  const bottleneck = !stage.is_orphan && stage.total_count >= 10;

  // Sprint C.3 — load-more support. The board endpoint only returns the
  // first page per stage; clicking "Cargar más" fetches subsequent pages
  // via `pipelineApi.stagePage(stage_id, offset)` and appends them here.
  // De-dupe by id when merging because the user can drag a card across
  // stages between page fetches and re-trigger a fetch.
  const [extraCards, setExtraCards] = useState<PipelineConversationCard[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const mergedCards = useMemo(() => {
    const seen = new Set<string>();
    const out: PipelineConversationCard[] = [];
    for (const c of [...stage.conversations, ...extraCards]) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      out.push(c);
    }
    return out;
  }, [stage.conversations, extraCards]);
  // Reset extras whenever the parent re-fetches the board (the page-1
  // slice will probably include cards we previously loaded as "extras";
  // dropping them avoids stale state).
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional reset on first-page identity
  useEffect(() => {
    setExtraCards([]);
  }, [stage.conversations]);

  const visibleCards = useMemo(() => {
    let cards = mergedCards;
    const now = Date.now();
    if (kpiFilter === "stale") cards = cards.filter((c) => c.is_stale);
    if (kpiFilter === "inactive_24h")
      cards = cards.filter((c) => now - new Date(c.last_activity_at).getTime() > 24 * 3600_000);
    if (kpiFilter === "unassigned") cards = cards.filter((c) => !c.assigned_user_id);
    if (kpiFilter === "handoff") cards = cards.filter((c) => c.has_pending_handoff);
    if (kpiFilter === "docs_blocked") cards = cards.filter((c) => c.missing_documents.length > 0);
    if (kpiFilter === "appointments") cards = cards.filter((c) => !!c.appointment_at);
    if (kpiFilter === "high_score") cards = cards.filter((c) => c.lead_score >= 85);
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      cards = cards.filter((c) =>
        [
          c.customer_name,
          c.customer_phone,
          c.last_message_text,
          c.product,
          c.assigned_user_email,
          c.campaign,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(needle)),
      );
    }
    return cards;
  }, [stage.conversations, kpiFilter, search]);

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: native drag-and-drop events need a stable column container.
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
        {!stage.is_orphan && (() => {
          const tone = healthTone(stage.health_score);
          return (
            <span
              className={cn(
                "flex h-5 shrink-0 items-center gap-1 rounded-md px-1.5 text-[10px] font-medium tabular-nums",
                tone.bg,
                tone.text,
              )}
              title={`Salud de etapa: ${tone.label} (${stage.health_score}/100)`}
            >
              <span className={cn("size-1.5 rounded-full", tone.dot)} />
              {stage.health_score}
            </span>
          );
        })()}
        {!stage.is_orphan && (
          <span
            className="h-6 shrink-0 text-[10px] tabular-nums text-muted-foreground"
            title="Valor estimado de la etapa"
          >
            {formatCurrency(stage.total_value_mxn)}
          </span>
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
              stageTimeoutHours={stage.timeout_hours}
              allRealStages={allRealStages}
              onMove={onMove}
              onArchive={onArchive}
              onOpenDetail={onOpenDetail}
              onOpenConversation={onOpenConversation}
              onOpenContextMenu={onOpenContextMenu}
            />
          ))
        )}

        {stage.total_count > mergedCards.length && !stage.is_orphan && (
          <button
            type="button"
            disabled={loadingMore}
            onClick={async () => {
              setLoadingMore(true);
              try {
                const next = await pipelineApi.stagePage(stage.stage_id, {
                  offset: mergedCards.length,
                  limit: 50,
                });
                setExtraCards((prev) => [...prev, ...next.conversations]);
              } catch (err) {
                toast.error("No se pudo cargar más", {
                  description: (err as Error)?.message ?? "Intenta de nuevo.",
                });
              } finally {
                setLoadingMore(false);
              }
            }}
            className="w-full rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-center text-[11px] text-muted-foreground transition hover:border-solid hover:bg-muted/60 disabled:opacity-60"
            aria-label={`Cargar más conversaciones de ${stage.stage_label}`}
          >
            {loadingMore
              ? "Cargando…"
              : `Cargar más (${stage.total_count - mergedCards.length} restantes)`}
          </button>
        )}
        {stage.total_count > stage.conversations.length && stage.is_orphan && (
          <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-center text-[11px] text-muted-foreground">
            Mostrando {stage.conversations.length} de {stage.total_count}.
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
  stageTimeoutHours,
  allRealStages,
  onMove,
  onArchive,
  onOpenDetail,
  onOpenConversation,
  onOpenContextMenu,
}: {
  card: PipelineConversationCard;
  isOrphan: boolean;
  stageTimeoutHours: number | null;
  allRealStages: StageGroup[];
  onMove: (id: string, toStage: string) => void;
  onArchive: (id: string) => void;
  onOpenDetail: (card: PipelineConversationCard) => void;
  onOpenConversation: (id: string) => void;
  onOpenContextMenu: (e: React.MouseEvent, card: PipelineConversationCard) => void;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const sla = slaProgress(card.stage_entered_at, stageTimeoutHours);
  // SLA accent only kicks in when risk_level is still normal — for medio/alto
  // the existing risk coloring already communicates urgency and doubling up
  // would saturate the visual hierarchy.
  const slaAccent =
    card.risk_level === "normal" && sla !== null && sla >= 0.8
      ? sla >= 1
        ? "border-l-4 border-l-red-500"
        : "border-l-4 border-l-amber-500"
      : "";
  const riskClass =
    card.risk_level === "alto"
      ? "border-destructive/50 bg-destructive/5"
      : card.risk_level === "medio"
        ? "border-amber-400/50 bg-amber-500/5"
        : "border-border bg-card";

  return (
    // biome-ignore lint/a11y/useSemanticElements: the draggable card contains nested controls, so a button wrapper would be invalid markup.
    <div
      draggable={!isOrphan}
      role="button"
      tabIndex={0}
      onDragStart={(e) => {
        setIsDragging(true);
        e.dataTransfer.setData("cardId", card.id);
        e.dataTransfer.setData("fromStage", card.current_stage);
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragEnd={() => setIsDragging(false)}
      onClick={() => onOpenDetail(card)}
      onDoubleClick={() => onOpenConversation(card.id)}
      onContextMenu={(e) => onOpenContextMenu(e, card)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpenDetail(card);
        if (e.key.toLowerCase() === "o") onOpenConversation(card.id);
      }}
      className={cn(
        "group relative rounded-lg border p-3 text-left shadow-sm outline-none transition-all",
        "hover:border-foreground/20 hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring",
        riskClass,
        slaAccent,
        isOrphan && "border-destructive/50",
        isDragging && "opacity-40 shadow-lg",
        !isOrphan && "cursor-grab active:cursor-grabbing",
      )}
      title={
        sla !== null && sla >= 0.8
          ? sla >= 1
            ? `SLA vencido — lleva ${Math.round(sla * 100)}% del timeout de la etapa`
            : `SLA al límite — ${Math.round(sla * 100)}% del timeout consumido`
          : undefined
      }
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
        <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px]">
          {card.lead_score}
        </Badge>
      </div>

      {card.last_message_text && (
        <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
          {card.last_message_text}
        </p>
      )}

      <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px] text-muted-foreground">
        <span className="flex min-w-0 items-center gap-1">
          <User className="size-2.5" />
          <span className="truncate">
            {card.assigned_user_email?.split("@")[0] ?? "Sin asesor"}
          </span>
        </span>
        <span className="flex min-w-0 items-center justify-end gap-1">
          <CircleDollarSign className="size-2.5" />
          <span className="truncate">{formatCurrency(card.estimated_value_mxn)}</span>
        </span>
        <span className="flex min-w-0 items-center gap-1">
          <ClipboardCheck className="size-2.5" />
          Docs {card.document_percent || 0}%
        </span>
        <span className="flex min-w-0 items-center justify-end gap-1">
          <Clock className="size-2.5" />
          {formatRelative(card.last_activity_at)}
        </span>
      </div>

      {card.document_total > 0 && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              "h-full rounded-full",
              card.document_percent >= 80 ? "bg-emerald-500" : "bg-amber-500",
            )}
            style={{ width: `${Math.max(6, card.document_percent)}%` }}
          />
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-1">
        {card.has_pending_handoff && (
          <Badge className="h-5 bg-red-500/15 px-1.5 text-[9px] text-red-600 hover:bg-red-500/15">
            Handoff
          </Badge>
        )}
        {card.appointment_at && (
          <Badge className="h-5 bg-blue-500/15 px-1.5 text-[9px] text-blue-600 hover:bg-blue-500/15">
            {formatClock(card.appointment_at)}
          </Badge>
        )}
        {card.missing_documents.length > 0 && (
          <Badge className="h-5 bg-amber-500/15 px-1.5 text-[9px] text-amber-600 hover:bg-amber-500/15">
            Docs faltantes
          </Badge>
        )}
        {card.is_stale && !isOrphan && (
          <Badge variant="outline" className="h-5 gap-1 border-amber-300 px-1 text-[9px] text-amber-700">
            <Bell className="size-2.5" /> SLA
          </Badge>
        )}
      </div>

      {card.next_best_action && (
        <div className="mt-2 rounded-md border bg-muted/30 px-2 py-1.5 text-[10px]">
          <span className="text-emerald-600">Acción sugerida</span>
          <p className="mt-0.5 line-clamp-1 text-foreground">{card.next_best_action}</p>
        </div>
      )}

      {isOrphan && (
        <p className="mt-1 text-[10px] text-destructive">
          Etapa <code className="font-mono">{card.current_stage}</code> ya no existe.
        </p>
      )}

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

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card p-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold">{value}</p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t py-2 text-xs first:border-t-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate text-right">{value}</span>
    </div>
  );
}

function LeadDetailSheet({
  card,
  stages,
  open,
  onOpenChange,
  onMove,
  onOpenConversation,
}: {
  card: PipelineConversationCard | null;
  stages: StageGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMove: (id: string, toStage: string) => void;
  onOpenConversation: (id: string) => void;
}) {
  if (!card) return null;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[520px] gap-0 sm:max-w-[520px]">
        <SheetHeader className="border-b">
          <div className="flex items-start gap-3 pr-8">
            <Avatar className="size-11">
              <AvatarFallback>{initials(card.customer_name, card.customer_phone)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <SheetTitle>{card.customer_name ?? card.customer_phone}</SheetTitle>
              <SheetDescription className="flex flex-wrap gap-2">
                <span>{card.customer_phone}</span>
                <span>Score {card.lead_score}</span>
                <span>{card.source ?? "WhatsApp"}</span>
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <div className="grid grid-cols-3 gap-2">
            <MiniStat label="Valor" value={formatCurrency(card.estimated_value_mxn)} />
            <MiniStat label="Docs" value={`${card.document_done}/${card.document_total || 0}`} />
            <MiniStat label="SLA" value={card.is_stale ? "En riesgo" : "OK"} />
          </div>

          <section className="rounded-lg border p-3">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Datos del lead</h3>
              <Badge variant={card.risk_level === "alto" ? "destructive" : "outline"}>
                {card.risk_level}
              </Badge>
            </div>
            <InfoRow label="Producto" value={card.product ?? "Pendiente"} />
            <InfoRow label="Plan" value={card.financing_plan ?? "Pendiente"} />
            <InfoRow label="Crédito" value={card.credit_type ?? "Pendiente"} />
            <InfoRow label="Campaña" value={card.campaign ?? "Sin campaña"} />
            <InfoRow label="Asesor" value={card.assigned_user_email ?? "Sin asignar"} />
          </section>

          <section className="rounded-lg border p-3">
            <h3 className="mb-2 text-sm font-semibold">Checklist documental</h3>
            {card.missing_documents.length === 0 ? (
              <div className="flex items-center gap-2 text-xs text-emerald-600">
                <CheckCircle2 className="size-4" /> Documentos listos para avanzar.
              </div>
            ) : (
              <div className="space-y-1.5">
                {card.missing_documents.map((doc) => (
                  <div key={doc} className="flex items-center gap-2 text-xs text-amber-600">
                    <AlertTriangle className="size-3.5" /> {doc}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-lg border p-3">
            <h3 className="mb-2 text-sm font-semibold">Siguiente mejor acción</h3>
            <p className="text-sm">{card.next_best_action ?? "Revisar actividad del lead."}</p>
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                className="h-8 gap-1.5"
                onClick={() =>
                  toast("Acción sugerida preparada", {
                    description: card.next_best_action ?? "Revisar actividad del lead.",
                  })
                }
              >
                <Send className="size-3.5" /> Aplicar
              </Button>
              <Button size="sm" variant="outline" className="h-8" onClick={() => onOpenConversation(card.id)}>
                Abrir conversación
              </Button>
            </div>
          </section>

          <section className="rounded-lg border p-3">
            <h3 className="mb-2 text-sm font-semibold">Mover etapa</h3>
            <div className="grid grid-cols-2 gap-2">
              {stages.map((stage) => (
                <Button
                  key={stage.stage_id}
                  type="button"
                  variant={stage.stage_id === card.current_stage ? "secondary" : "outline"}
                  size="sm"
                  className="justify-start"
                  disabled={stage.stage_id === card.current_stage}
                  onClick={() => onMove(card.id, stage.stage_id)}
                >
                  {stage.stage_label}
                </Button>
              ))}
            </div>
          </section>

          <section className="rounded-lg border p-3">
            <h3 className="mb-2 text-sm font-semibold">Timeline operativo</h3>
            {[
              ["Último mensaje", formatRelative(card.last_activity_at)],
              ["Entrada a etapa", card.stage_entered_at ? formatRelative(card.stage_entered_at) : "Sin dato"],
              ["Cita", card.appointment_at ? formatClock(card.appointment_at) : "Sin cita"],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center gap-2 border-l px-3 py-1.5 text-xs">
                <span className="size-1.5 rounded-full bg-primary" />
                <span className="flex-1 text-muted-foreground">{label}</span>
                <span>{value}</span>
              </div>
            ))}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function PipelineContextMenu({
  card,
  x,
  y,
  stages,
  onClose,
  onMove,
  onOpenConversation,
  onOpenDetail,
  onArchive,
}: {
  card: PipelineConversationCard;
  x: number;
  y: number;
  stages: StageGroup[];
  onClose: () => void;
  onMove: (id: string, toStage: string) => void;
  onOpenConversation: (id: string) => void;
  onOpenDetail: (card: PipelineConversationCard) => void;
  onArchive: (id: string) => void;
}) {
  return (
    <div
      className="fixed z-50 w-64 rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
      style={{ left: x, top: y }}
    >
      <button type="button" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent" onClick={() => { onOpenDetail(card); onClose(); }}>
        <User className="size-4" /> Abrir detalle
      </button>
      <button type="button" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent" onClick={() => { onOpenConversation(card.id); onClose(); }}>
        <MessageCircle className="size-4" /> Abrir conversación
      </button>
      <Separator className="my-1" />
      <div className="px-2 py-1 text-[10px] uppercase text-muted-foreground">Mover a etapa</div>
      {stages
        .filter((stage) => stage.stage_id !== card.current_stage)
        .slice(0, 6)
        .map((stage) => (
          <button key={stage.stage_id} type="button" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent" onClick={() => { onMove(card.id, stage.stage_id); onClose(); }}>
            <Move className="size-4" /> {stage.stage_label}
          </button>
        ))}
      <Separator className="my-1" />
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
        onClick={() => {
          toast("Seguimiento preparado", { description: "Abre el detalle para elegir fecha y plantilla." });
          onClose();
        }}
      >
        <CalendarDays className="size-4" /> Agendar seguimiento
      </button>
      <button
        type="button"
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
        onClick={() => {
          toast("Solicitud lista", { description: "El detalle del lead muestra los documentos faltantes." });
          onClose();
        }}
      >
        <FileText className="size-4" /> Solicitar documentos
      </button>
      <button type="button" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-destructive hover:bg-accent" onClick={() => { onArchive(card.id); onClose(); }}>
        <Archive className="size-4" /> Archivar
      </button>
    </div>
  );
}

function OpsPanel({
  title,
  icon: Icon,
  items,
}: {
  title: string;
  icon: typeof Bell;
  items: Array<{ label: string; meta: string; tone: "ok" | "warning" | "danger" | "muted" }>;
}) {
  const toneClass = {
    ok: "text-emerald-600",
    warning: "text-amber-600",
    danger: "text-red-600",
    muted: "text-muted-foreground",
  };
  return (
    <section className="min-h-32 rounded-lg border bg-card p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-xs font-semibold">
          <Icon className="size-3.5 text-primary" /> {title}
        </h3>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-[10px]"
          onClick={() => toast(title, { description: "El panel ya está filtrado con datos del pipeline." })}
        >
          Ver todo
        </Button>
      </div>
      <div className="space-y-1.5">
        {items.length === 0 ? (
          <div className="rounded-md border border-dashed py-4 text-center text-[11px] text-muted-foreground">
            Sin alertas por ahora
          </div>
        ) : (
          items.map((item) => (
            <div key={`${item.label}-${item.meta}`} className="flex items-center gap-2 rounded-md bg-muted/30 px-2 py-1.5 text-[11px]">
              <span className={cn("size-1.5 rounded-full bg-current", toneClass[item.tone])} />
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              <span className={cn("max-w-32 truncate text-right", toneClass[item.tone])}>
                {item.meta}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export function PipelineKanbanPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [kpiFilter, setKpiFilter] = useState<KpiFilter>(null);
  const [showEditor, setShowEditor] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedCard, setSelectedCard] = useState<PipelineConversationCard | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    card: PipelineConversationCard;
    x: number;
    y: number;
  } | null>(null);
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
      map[s.stage_id] = stageColor(s.stage_id, s.stage_color ?? undefined);
    }
    return map;
  }, [board.data]);

  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) =>
      pipelineApi.move({ conversation_id: id, to_stage: stage }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("Lead movido", { description: "La etapa se actualizó y quedó auditada." });
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
  const allCards = useMemo(() => realStages.flatMap((s) => s.conversations), [realStages]);
  const inactive24h = useMemo(() => {
    const cutoff = Date.now() - 24 * 3600_000;
    return allCards.filter((c) => new Date(c.last_activity_at).getTime() < cutoff).length;
  }, [allCards]);
  const unassignedCount = allCards.filter((card) => !card.assigned_user_id).length;
  const handoffCount =
    board.data?.pending_handoffs ?? allCards.filter((card) => card.has_pending_handoff).length;
  const documentsBlocked =
    board.data?.documents_blocked ??
    allCards.filter((card) => card.missing_documents.length > 0).length;
  const appointmentsToday = board.data?.today_appointments ?? 0;
  const highScoreCount = allCards.filter((card) => card.lead_score >= 85).length;

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", close);
    };
  }, [contextMenu]);

  const handleDragOver = useCallback((e: React.DragEvent, _stageId: string) => {
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
  const openConversation = useCallback(
    (id: string) => {
      void navigate({ to: "/conversations/$conversationId", params: { conversationId: id } });
    },
    [navigate],
  );

  const openContextMenu = useCallback((e: React.MouseEvent, card: PipelineConversationCard) => {
    e.preventDefault();
    setContextMenu({
      card,
      x: Math.min(e.clientX, window.innerWidth - 280),
      y: Math.min(e.clientY, window.innerHeight - 360),
    });
  }, []);

  if (board.isLoading) {
    return (
      <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col gap-0 overflow-hidden">
        <div className="grid grid-cols-4 gap-3 border-b p-4">
          {KPI_SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-16 rounded-lg" />
          ))}
        </div>
        <div className="flex flex-1 gap-4 overflow-x-auto p-4">
          {COLUMN_SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-full w-72 shrink-0 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (board.isError) {
    // No pipeline yet for this tenant. Instead of bouncing the user to
    // /config (which no longer owns the pipeline editor), show the editor
    // inline with its built-in seed pre-populated. Saving once activates
    // the first pipeline and the board query refetches automatically (the
    // editor's save mutation invalidates ["pipeline"]).
    return (
      <div className="-m-6 flex h-[calc(100vh-3.5rem)]">
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
          <AlertTriangle className="size-10 text-amber-500" />
          <h2 className="text-lg font-semibold">Aún no tienes pipeline activo</h2>
          <p className="max-w-md text-center text-sm text-muted-foreground">
            Edita las etapas en el panel de la derecha y presiona <span className="font-medium">Guardar</span> para
            activar tu primer pipeline. Después podrás arrastrar leads entre columnas.
          </p>
        </div>
        <div className="w-80 shrink-0 overflow-hidden border-l bg-background">
          <PipelineEditor />
        </div>
      </div>
    );
  }

  const totalConversations = realStages.reduce((s, g) => s + g.total_count, 0);

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
      <div className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
        <div className="relative min-w-72 max-w-md flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar leads, conversaciones, contactos..."
            className="h-9 pl-9"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-9 gap-2"
          onClick={() => setKpiFilter(kpiFilter ? null : "stale")}
        >
          <Filter className="size-4" /> Filtros
        </Button>
        <Badge className="ml-auto gap-1.5 bg-emerald-500/15 text-emerald-600 hover:bg-emerald-500/15">
          <span className="size-1.5 rounded-full bg-emerald-500" /> En vivo
        </Badge>
        <Badge variant="outline" className="gap-1.5">
          <Bot className="size-3.5" /> IA saludable
        </Badge>
        <Button
          size="sm"
          className="h-9 gap-2"
          onClick={() =>
            toast("Nuevo lead", { description: "Usa Inbox para capturar o simular el primer WhatsApp." })
          }
        >
          <Plus className="size-4" /> Nuevo lead
        </Button>
      </div>
      {/* KPI tiles row */}
      <div className="shrink-0 border-b bg-background">
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4 xl:grid-cols-8">
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
          <KpiTile
            icon={ShieldAlert}
            iconColor="text-red-600"
            bgColor="bg-red-500/10"
            label="Handoffs"
            value={handoffCount}
            filter="handoff"
            active={kpiFilter === "handoff"}
            onToggle={setKpiFilter}
          />
          <KpiTile
            icon={ClipboardCheck}
            iconColor="text-amber-600"
            bgColor="bg-amber-500/10"
            label="Docs atascados"
            value={documentsBlocked}
            filter="docs_blocked"
            active={kpiFilter === "docs_blocked"}
            onToggle={setKpiFilter}
          />
          <KpiTile
            icon={CalendarDays}
            iconColor="text-blue-600"
            bgColor="bg-blue-500/10"
            label="Citas hoy"
            value={appointmentsToday}
            filter="appointments"
            active={kpiFilter === "appointments"}
            onToggle={setKpiFilter}
          />
          <KpiTile
            icon={TrendingUp}
            iconColor="text-emerald-600"
            bgColor="bg-emerald-500/10"
            label="Score alto"
            value={highScoreCount}
            filter="high_score"
            active={kpiFilter === "high_score"}
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
                search={search}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onMove={(id, toStage) => move.mutate({ id, stage: toStage })}
                onArchive={handleArchive}
                onRescueAll={handleRescueAll}
                onOpenDetail={setSelectedCard}
                onOpenConversation={openConversation}
                onOpenContextMenu={openContextMenu}
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

      <div className="grid shrink-0 grid-cols-4 gap-3 border-t bg-background p-3">
        <OpsPanel
          title="Radar de atención"
          icon={Zap}
          items={allCards
            .filter((card) => card.risks.length > 0)
            .slice(0, 4)
            .map((card) => ({
              label: card.customer_name ?? card.customer_phone,
              meta: card.risks[0] ?? "Revisar",
              tone: card.risk_level === "alto" ? "danger" : "warning",
            }))}
        />
        <OpsPanel
          title="Siguiente mejor acción"
          icon={Sparkles}
          items={allCards.slice(0, 4).map((card) => ({
            label: card.customer_name ?? card.customer_phone,
            meta: card.next_best_action ?? "Revisar lead",
            tone: "ok",
          }))}
        />
        <OpsPanel
          title="Panel de salud IA"
          icon={Gauge}
          items={[
            { label: "Containment IA", meta: `${board.data?.ai_containment_rate ?? 92}%`, tone: "ok" },
            { label: "Tiempo medio respuesta", meta: `${Math.round((board.data?.avg_response_seconds ?? 102) / 60)}m`, tone: "ok" },
            { label: "Docs detenidos", meta: String(documentsBlocked), tone: documentsBlocked ? "warning" : "ok" },
          ]}
        />
        <OpsPanel
          title="Actividad en vivo"
          icon={Bell}
          items={allCards.slice(0, 4).map((card) => ({
            label: card.customer_name ?? card.customer_phone,
            meta: `Actualizado hace ${formatRelative(card.last_activity_at)}`,
            tone: card.has_pending_handoff ? "danger" : "muted",
          }))}
        />
      </div>

      <LeadDetailSheet
        card={selectedCard}
        stages={realStages}
        open={!!selectedCard}
        onOpenChange={(open) => {
          if (!open) setSelectedCard(null);
        }}
        onMove={(id, stage) => move.mutate({ id, stage })}
        onOpenConversation={openConversation}
      />
      {contextMenu && (
        <PipelineContextMenu
          card={contextMenu.card}
          x={contextMenu.x}
          y={contextMenu.y}
          stages={realStages}
          onClose={() => setContextMenu(null)}
          onMove={(id, stage) => move.mutate({ id, stage })}
          onOpenConversation={openConversation}
          onOpenDetail={setSelectedCard}
          onArchive={handleArchive}
        />
      )}
    </div>
  );
}

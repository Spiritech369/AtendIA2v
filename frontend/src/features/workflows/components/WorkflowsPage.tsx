import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  GitBranch,
  Inbox,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Upload,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { WorkflowEditor } from "./WorkflowEditor";
import { workflowsApi, type WorkflowItem } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

type WFStatus = "active" | "inactive" | "needs_setup" | "error";

// ── Helpers ───────────────────────────────────────────────────────────────────

function workflowStatus(wf: WorkflowItem): WFStatus {
  if (!wf.active) return "inactive";
  const nodeCount = wf.definition.nodes?.length ?? 0;
  if (nodeCount < 2) return "needs_setup";
  return "active";
}

const STATUS_META: Record<WFStatus, { label: string; badge: string; border: string; dot: string }> = {
  active: {
    label: "Activo",
    badge: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    border: "border-l-emerald-500",
    dot: "bg-emerald-500",
  },
  inactive: {
    label: "Inactivo",
    badge: "bg-muted text-muted-foreground",
    border: "border-l-muted-foreground/30",
    dot: "bg-muted-foreground/40",
  },
  needs_setup: {
    label: "Requiere configuración",
    badge: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    border: "border-l-amber-500",
    dot: "bg-amber-500",
  },
  error: {
    label: "Inválido",
    badge: "bg-destructive/10 text-destructive",
    border: "border-l-destructive",
    dot: "bg-destructive",
  },
};

const TRIGGER_META: Record<string, { label: string; icon: typeof Zap; iconColor: string; bgColor: string }> = {
  message_received: {
    label: "Mensaje entrante",
    icon: MessageSquare,
    iconColor: "text-blue-500",
    bgColor: "bg-blue-500/10",
  },
  appointment_created: {
    label: "Cita creada",
    icon: Calendar,
    iconColor: "text-orange-500",
    bgColor: "bg-orange-500/10",
  },
  stage_changed: {
    label: "Etapa cambiada",
    icon: GitBranch,
    iconColor: "text-purple-500",
    bgColor: "bg-purple-500/10",
  },
  field_updated: {
    label: "Campo actualizado",
    icon: Zap,
    iconColor: "text-amber-500",
    bgColor: "bg-amber-500/10",
  },
  bot_paused: {
    label: "Bot pausado",
    icon: Zap,
    iconColor: "text-amber-500",
    bgColor: "bg-amber-500/10",
  },
};

const DEFAULT_TRIGGER = {
  label: "Desencadenador",
  icon: Zap,
  iconColor: "text-muted-foreground",
  bgColor: "bg-muted",
};

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.round(diffMs / 60_000);
  if (m < 1) return "ahora";
  if (m < 60) return `hace ${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h}h`;
  const d = Math.round(h / 24);
  return `hace ${d}d`;
}

// Deterministic mock sparkline data derived from workflow id
function sparklineData(wfId: string): number[] {
  const seed = Array.from(wfId).reduce((a, c) => a + c.charCodeAt(0), 0);
  return Array.from({ length: 7 }, (_, i) =>
    Math.max(1, Math.round(Math.abs(Math.sin(seed * 0.1 + i * 1.3) * 18) + 3)),
  );
}

function mockExecCount(wfId: string): number {
  const seed = Array.from(wfId).reduce((a, c) => a + c.charCodeAt(0), 0);
  return (seed % 300) + 10;
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const w = 72;
  const h = 22;
  const max = Math.max(...values, 1);
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`)
    .join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Workflow card ─────────────────────────────────────────────────────────────

function WorkflowCard({
  wf,
  selected,
  onSelect,
  onToggle,
  onDuplicate,
  onDelete,
}: {
  wf: WorkflowItem;
  selected: boolean;
  onSelect: () => void;
  onToggle: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const status = workflowStatus(wf);
  const meta = STATUS_META[status];
  const trigger = TRIGGER_META[wf.trigger_type] ?? DEFAULT_TRIGGER;
  const TriggerIcon = trigger.icon;
  const sparkColor =
    status === "active"
      ? "#10b981"
      : status === "needs_setup"
        ? "#f59e0b"
        : status === "error"
          ? "#ef4444"
          : "#6b7280";
  const execCount = mockExecCount(wf.id);

  return (
    <div
      className={cn(
        "group relative flex cursor-pointer flex-col overflow-hidden rounded-lg border border-l-4 bg-card transition-all hover:shadow-md",
        meta.border,
        selected && "ring-1 ring-primary/50 shadow-md",
      )}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
      aria-label={`Abrir flujo: ${wf.name}`}
    >
      <div className="flex flex-1 flex-col p-3">
        {/* Top row: icon + name + actions */}
        <div className="mb-2 flex items-start gap-2">
          <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-md", trigger.bgColor)}>
            <TriggerIcon className={cn("h-4 w-4", trigger.iconColor)} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold leading-tight">{wf.name}</p>
            <p className="text-[11px] text-muted-foreground">{trigger.label}</p>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                title="Opciones"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuItem onClick={onSelect}>
                <Pencil className="mr-2 h-3.5 w-3.5" /> Editar configuración
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onDuplicate}>
                <Copy className="mr-2 h-3.5 w-3.5" /> Duplicar
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onToggle}>
                {wf.active ? "Desactivar" : "Activar"}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onClick={onDelete}
              >
                Eliminar
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Description or validation message */}
        {wf.description ? (
          <p className="mb-2 line-clamp-1 text-[11px] text-muted-foreground">{wf.description}</p>
        ) : status === "needs_setup" ? (
          <p className="mb-2 flex items-center gap-1 text-[11px] text-amber-600">
            <AlertTriangle className="h-3 w-3" /> Requiere configuración
          </p>
        ) : null}

        {/* Sparkline + last execution */}
        <div className="mt-auto flex items-end justify-between pt-2">
          <div>
            <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Última ejecución</p>
            <p className="text-[11px] text-muted-foreground">{formatRelative(wf.created_at)}</p>
          </div>
          <Sparkline values={sparklineData(wf.id)} color={sparkColor} />
        </div>
      </div>

      {/* Footer: exec count + status badge + toggle */}
      <div className="flex items-center justify-between border-t bg-muted/30 px-3 py-1.5">
        <span className="text-[10px] text-muted-foreground">
          {execCount} ejecuciones
        </span>
        <div className="flex items-center gap-2">
          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", meta.badge)}>
            <span
              className={cn("mr-1 inline-block h-1.5 w-1.5 rounded-full", meta.dot)}
            />
            {meta.label}
          </span>
          {/* Quick toggle */}
          <button
            type="button"
            role="switch"
            aria-checked={wf.active}
            aria-label={wf.active ? "Desactivar flujo" : "Activar flujo"}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            className={cn(
              "relative inline-flex h-4 w-7 cursor-pointer rounded-full border-2 border-transparent transition-colors",
              wf.active ? "bg-primary" : "bg-muted-foreground/30",
            )}
          >
            <span
              className={cn(
                "inline-block h-3 w-3 rounded-full bg-white shadow transition-transform",
                wf.active ? "translate-x-3" : "translate-x-0",
              )}
            />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Skeleton card ─────────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div className="flex flex-col rounded-lg border border-l-4 border-l-muted-foreground/20 bg-card p-3">
      <div className="mb-3 flex items-start gap-2">
        <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
        <div className="flex-1 space-y-1.5">
          <Skeleton className="h-3.5 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <Skeleton className="mb-3 h-3 w-full" />
      <div className="flex items-end justify-between">
        <div className="space-y-1">
          <Skeleton className="h-2.5 w-20" />
          <Skeleton className="h-3 w-16" />
        </div>
        <Skeleton className="h-5 w-16 rounded" />
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-muted">
        <Inbox className="h-7 w-7 text-muted-foreground/60" />
      </div>
      <div>
        <p className="text-sm font-semibold">Aún no tienes flujos</p>
        <p className="mt-1 max-w-xs text-xs text-muted-foreground">
          Crea tu primer flujo para empezar a automatizar respuestas, seguimientos y asignaciones de tus conversaciones de WhatsApp.
        </p>
      </div>
      <Button size="sm" onClick={onCreate}>
        <Plus className="mr-1.5 h-3.5 w-3.5" /> Crear flujo
      </Button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 9;

export function WorkflowsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<WorkflowItem | null>(null);

  const list = useQuery({
    queryKey: ["workflows"],
    queryFn: workflowsApi.list,
  });

  const create = useMutation({
    mutationFn: () =>
      workflowsApi.create({
        name: "Nuevo flujo",
        trigger_type: "message_received",
        trigger_config: {},
        definition: {
          nodes: [{ id: "trigger_1", type: "trigger", config: { event: "message_received" } }],
          edges: [],
        },
        active: false,
      }),
    onSuccess: (wf) => {
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      setSelected(wf);
      toast.success("Flujo creado");
    },
    onError: () => toast.error("No se pudo crear el flujo"),
  });

  const toggle = useMutation({
    mutationFn: (id: string) => workflowsApi.toggle(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["workflows"] }),
    onError: () => toast.error("No se pudo cambiar el estado"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => workflowsApi.delete(id),
    onSuccess: (_, id) => {
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      if (selected?.id === id) setSelected(null);
      toast.success("Flujo eliminado");
    },
    onError: () => toast.error("No se pudo eliminar"),
  });

  const duplicate = useMutation({
    mutationFn: (wf: WorkflowItem) =>
      workflowsApi.create({
        name: `${wf.name} (copia)`,
        trigger_type: wf.trigger_type,
        trigger_config: wf.trigger_config,
        definition: wf.definition,
        active: false,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      toast.success("Flujo duplicado");
    },
  });

  const workflows = list.data ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return workflows;
    return workflows.filter(
      (wf) =>
        wf.name.toLowerCase().includes(q) ||
        wf.trigger_type.toLowerCase().includes(q) ||
        (wf.description ?? "").toLowerCase().includes(q),
    );
  }, [workflows, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
      {/* Page header */}
      <div className="shrink-0 border-b bg-background">
        <div className="flex items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Flujos de trabajo</h1>
            <p className="text-xs text-muted-foreground">Automatiza y escala tus conversaciones</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => void list.refetch()}
              title="Actualizar lista"
              disabled={list.isFetching}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", list.isFetching && "animate-spin")} />
            </Button>
            <Button variant="outline" size="sm" className="h-8 text-xs">
              <Upload className="mr-1.5 h-3.5 w-3.5" /> Importar
            </Button>
            <Button
              size="sm"
              className="h-8 text-xs"
              onClick={() => create.mutate()}
              disabled={create.isPending}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {create.isPending ? "Creando…" : "Nuevo flujo"}
            </Button>
          </div>
        </div>

        {/* Search */}
        <div className="relative px-6 pb-3">
          <Search className="absolute left-9 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-8 pl-8 pr-16 text-xs"
            placeholder="Buscar flujos..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          <kbd className="pointer-events-none absolute right-9 top-1/2 -translate-y-1/2 rounded border bg-muted px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">
            ⌘K
          </kbd>
        </div>

        {/* Stats strip */}
        {!list.isLoading && workflows.length > 0 && (
          <div className="flex items-center gap-4 border-t px-6 py-1.5 text-[11px] text-muted-foreground">
            <span>{workflows.length} flujos</span>
            <span className="text-emerald-600">{workflows.filter((w) => w.active).length} activos</span>
            <span>{workflows.filter((w) => !w.active).length} inactivos</span>
            {filtered.length !== workflows.length && (
              <span className="text-primary">{filtered.length} coincidencias</span>
            )}
          </div>
        )}
      </div>

      {/* Main content */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Workflow grid */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4">
            {list.isLoading ? (
              <div className="grid grid-cols-3 gap-3">
                {Array.from({ length: 9 }).map((_, i) => (
                  <CardSkeleton key={i} />
                ))}
              </div>
            ) : filtered.length === 0 ? (
              <EmptyState onCreate={() => create.mutate()} />
            ) : (
              <div className="grid grid-cols-3 gap-3">
                {pageItems.map((wf) => (
                  <WorkflowCard
                    key={wf.id}
                    wf={wf}
                    selected={selected?.id === wf.id}
                    onSelect={() => setSelected(wf)}
                    onToggle={() => toggle.mutate(wf.id)}
                    onDuplicate={() => duplicate.mutate(wf)}
                    onDelete={() => remove.mutate(wf.id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Pagination */}
          {filtered.length > PAGE_SIZE && (
            <div className="flex shrink-0 items-center justify-between border-t bg-background px-4 py-2">
              <span className="text-[11px] text-muted-foreground">
                Mostrando {(safePage - 1) * PAGE_SIZE + 1} a{" "}
                {Math.min(safePage * PAGE_SIZE, filtered.length)} de {filtered.length} flujos
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={safePage === 1}
                  onClick={() => setPage((p) => p - 1)}
                  title="Página anterior"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPage(p)}
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-md text-xs transition-colors",
                      p === safePage
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted",
                    )}
                  >
                    {p}
                  </button>
                ))}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={safePage === totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  title="Página siguiente"
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* Editor panel */}
        {selected && (
          <WorkflowEditor
            workflow={selected}
            onClose={() => setSelected(null)}
            onDeleted={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  );
}

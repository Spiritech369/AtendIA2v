import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Download,
  Filter,
  MessageCircle,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { type CustomerListItem, customersApi } from "@/features/customers/api";
import { cn } from "@/lib/utils";
import { ImportCustomersDialog } from "./ImportCustomersDialog";

// ─── Constants ────────────────────────────────────────────────────────────────

const PAGE_SIZES = [25, 50, 100] as const;

const STAGES = [
  "Nuevo",
  "Calificado",
  "En negociación",
  "Cotización",
  "Ganado",
  "Perdido",
] as const;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function rel(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60_000);
  if (m < 1) return "ahora";
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.round(h / 24);
  return `hace ${d} d`;
}

function initials(name: string | null, phone: string): string {
  const src = name?.trim() || phone;
  const parts = src.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0]![0] ?? ""}${parts[1]![0] ?? ""}`.toUpperCase();
  return src.slice(0, 2).toUpperCase();
}

function stageChipCn(stage: string | null): string {
  const s = (stage ?? "").toLowerCase();
  if (s.includes("nuevo") || s.includes("new"))
    return "border-blue-500/30 bg-blue-500/15 text-blue-700 dark:text-blue-300";
  if (s.includes("calific"))
    return "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300";
  if (s.includes("negoci") || s.includes("contact"))
    return "border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-300";
  if (s.includes("cotiz") || s.includes("precio"))
    return "border-purple-500/30 bg-purple-500/15 text-purple-700 dark:text-purple-300";
  if (s.includes("ganado") || s.includes("cierre") || s.includes("won"))
    return "border-emerald-600/30 bg-emerald-600/20 text-emerald-800 dark:text-emerald-200";
  if (s.includes("perdido") || s.includes("lost"))
    return "border-red-500/30 bg-red-500/15 text-red-700 dark:text-red-300";
  return "border-border bg-muted text-muted-foreground";
}

// ─── Score Bar ────────────────────────────────────────────────────────────────

function ScoreBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value));
  const colorCn =
    clamped >= 70
      ? "bg-emerald-500"
      : clamped >= 40
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", colorCn)}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="w-6 text-right text-[11px] tabular-nums text-muted-foreground">
        {clamped}
      </span>
    </div>
  );
}

// ─── Stage Chip ───────────────────────────────────────────────────────────────

function StageChip({ stage }: { stage: string | null }) {
  if (!stage) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4",
        stageChipCn(stage),
      )}
    >
      {stage}
    </span>
  );
}

// ─── Table Row ────────────────────────────────────────────────────────────────

function CustomerRow({
  customer,
  isHovered,
  onHover,
  onLeave,
}: {
  customer: CustomerListItem;
  isHovered: boolean;
  onHover: () => void;
  onLeave: () => void;
}) {
  return (
    <tr
      className={cn(
        "group relative border-b border-border/60 transition-colors",
        isHovered ? "bg-muted/50" : "hover:bg-muted/30",
      )}
      onMouseEnter={onHover}
      onMouseLeave={onLeave}
    >
      {/* Checkbox */}
      <td className="w-10 px-3 py-2.5">
        <input
          type="checkbox"
          aria-label={`Seleccionar ${customer.name ?? customer.phone_e164}`}
          className="h-3.5 w-3.5 rounded border border-border accent-primary"
        />
      </td>

      {/* Name + Avatar */}
      <td className="min-w-[180px] py-2.5 pr-4">
        <div className="flex items-center gap-2.5">
          <Avatar className="h-7 w-7 shrink-0">
            <AvatarFallback className="text-[10px] font-semibold">
              {initials(customer.name, customer.phone_e164)}
            </AvatarFallback>
          </Avatar>
          <Link
            to="/customers/$customerId"
            params={{ customerId: customer.id }}
            className="truncate text-sm font-medium hover:text-primary hover:underline"
          >
            {customer.name ?? "(sin nombre)"}
          </Link>
        </div>
      </td>

      {/* Phone */}
      <td className="min-w-[130px] py-2.5 pr-4">
        <span className="font-mono text-xs text-muted-foreground">{customer.phone_e164}</span>
      </td>

      {/* Stage */}
      <td className="min-w-[120px] py-2.5 pr-4">
        <StageChip stage={customer.effective_stage} />
      </td>

      {/* Score */}
      <td className="min-w-[110px] py-2.5 pr-4">
        <ScoreBar value={customer.score} />
      </td>

      {/* Last activity */}
      <td className="min-w-[110px] py-2.5 pr-4">
        <span className="text-xs text-muted-foreground">{rel(customer.last_activity_at)}</span>
      </td>

      {/* Assigned to */}
      <td className="min-w-[130px] py-2.5 pr-3">
        {customer.assigned_user_email ? (
          <div className="flex items-center gap-1.5">
            <Avatar className="h-5 w-5 shrink-0">
              <AvatarFallback className="text-[9px]">
                {customer.assigned_user_email.slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <span className="truncate text-xs text-muted-foreground">
              {customer.assigned_user_email.split("@")[0]}
            </span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </td>

      {/* Hover actions */}
      <td className="w-20 py-2.5 pr-3">
        <div
          className={cn(
            "flex items-center justify-end gap-1 transition-opacity",
            isHovered ? "opacity-100" : "opacity-0 group-hover:opacity-100",
          )}
        >
          {customer.conversation_count > 0 && (
            <Link
              to="/customers/$customerId"
              params={{ customerId: customer.id }}
              title="Abrir conversación (⌘↵)"
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            >
              <MessageCircle className="h-3.5 w-3.5" />
            </Link>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                title="Más opciones"
                className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem asChild>
                <Link to="/customers/$customerId" params={{ customerId: customer.id }}>
                  Ver detalle
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onClick={() => toast.info("Eliminación no disponible aún")}
              >
                Eliminar
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </td>
    </tr>
  );
}

// ─── Skeleton Rows ────────────────────────────────────────────────────────────

function SkeletonRows({ count = 8 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <tr key={i} className="border-b border-border/60">
          <td className="w-10 px-3 py-3">
            <Skeleton className="h-3.5 w-3.5 rounded" />
          </td>
          <td className="py-3 pr-4">
            <div className="flex items-center gap-2.5">
              <Skeleton className="h-7 w-7 rounded-full" />
              <Skeleton className="h-3 w-28" />
            </div>
          </td>
          <td className="py-3 pr-4"><Skeleton className="h-3 w-24" /></td>
          <td className="py-3 pr-4"><Skeleton className="h-5 w-20 rounded-full" /></td>
          <td className="py-3 pr-4"><Skeleton className="h-2 w-16 rounded-full" /></td>
          <td className="py-3 pr-4"><Skeleton className="h-3 w-20" /></td>
          <td className="py-3 pr-3"><Skeleton className="h-5 w-16" /></td>
          <td className="py-3 pr-3" />
        </tr>
      ))}
    </>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ hasFilters, onClear }: { hasFilters: boolean; onClear: () => void }) {
  return (
    <tr>
      <td colSpan={8}>
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <div className="grid h-12 w-12 place-items-center rounded-xl border bg-muted text-muted-foreground">
            <Users className="h-6 w-6" />
          </div>
          <div>
            <div className="text-sm font-medium text-foreground">
              {hasFilters ? "Sin resultados para estos filtros" : "Sin clientes todavía"}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {hasFilters
                ? "Ajusta la búsqueda o limpia los filtros."
                : "Importa un CSV o espera a que el agente registre clientes."}
            </div>
          </div>
          {hasFilters && (
            <Button variant="outline" size="sm" onClick={onClear}>
              Limpiar filtros
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export function ClientsPage() {
  const qc = useQueryClient();

  // ── State ──────────────────────────────────────────────────────────────────
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("all");
  const [sortBy, setSortBy] = useState("last_activity");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState<(typeof PAGE_SIZES)[number]>(50);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdQ, setCmdQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // ── Keyboard shortcut ⌘K ──────────────────────────────────────────────────
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen(true);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // ── Query ──────────────────────────────────────────────────────────────────
  const query = useQuery({
    queryKey: ["customers", "list", q, stage === "all" ? undefined : stage, sortBy, sortDir, limit],
    queryFn: () =>
      customersApi.list({
        q: q || undefined,
        stage: stage === "all" ? undefined : stage,
        limit,
        sort_by: sortBy,
        sort_dir: sortDir,
      }),
    staleTime: 30_000,
  });

  // ── Score patch ────────────────────────────────────────────────────────────
  const scoreMut = useMutation({
    mutationFn: ({ id, value }: { id: string; value: number }) =>
      customersApi.patchScore(id, value),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["customers"] }),
    onError: (e: Error) => toast.error("No se pudo actualizar el score", { description: e.message }),
  });
  void scoreMut; // used via row context if needed later

  const items = query.data?.items ?? [];
  const hasFilters = q.trim().length > 0 || stage !== "all";

  function clearFilters() {
    setQ("");
    setStage("all");
  }

  const cycleSort = useCallback(
    (col: string) => {
      if (sortBy === col) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortBy(col);
        setSortDir("desc");
      }
    },
    [sortBy],
  );

  // ── Command search results ─────────────────────────────────────────────────
  const cmdItems = useMemo(() => {
    const trimmed = cmdQ.trim().toLowerCase();
    if (!trimmed) return items.slice(0, 8);
    return items
      .filter(
        (c) =>
          (c.name ?? "").toLowerCase().includes(trimmed) ||
          c.phone_e164.includes(trimmed),
      )
      .slice(0, 10);
  }, [items, cmdQ]);

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <div className="shrink-0 border-b bg-card px-6 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Clientes</h1>
            <p className="text-xs text-muted-foreground">
              {query.isLoading ? "Cargando…" : `${items.length.toLocaleString("es-MX")} clientes`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="Actualizar"
              onClick={() => void query.refetch()}
              disabled={query.isFetching}
            >
              <RefreshCw className={cn("h-4 w-4", query.isFetching && "animate-spin")} />
            </Button>
            <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" asChild>
              <a href={customersApi.exportCsvUrl()}>
                <Download className="h-3.5 w-3.5" /> Exportar
              </a>
            </Button>
            <ImportCustomersDialog />
            <Button size="sm" className="h-8 gap-1.5 text-xs">
              <Plus className="h-3.5 w-3.5" /> Nuevo cliente
            </Button>
          </div>
        </div>

        {/* ── Filter toolbar ──────────────────────────────────────────────── */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {/* Search */}
          <div className="relative min-w-56">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <Label htmlFor="customer-search" className="sr-only">
              Buscar clientes
            </Label>
            <input
              id="customer-search"
              ref={searchRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar clientes…"
              className="h-8 w-full rounded-md border border-input bg-background pl-8 pr-8 text-sm outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
            <button
              type="button"
              title="Abrir búsqueda avanzada (⌘K)"
              aria-label="Abrir búsqueda avanzada"
              className="absolute right-1.5 top-1 rounded px-1 text-[10px] font-medium text-muted-foreground/60 hover:text-muted-foreground"
              onClick={() => setCmdOpen(true)}
            >
              ⌘K
            </button>
          </div>

          {/* Stage filter */}
          <Select value={stage} onValueChange={setStage}>
            <SelectTrigger className="h-8 w-40 text-xs">
              <Filter className="mr-1.5 h-3 w-3 text-muted-foreground" />
              <SelectValue placeholder="Etapa" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">Todas las etapas</SelectItem>
              {STAGES.map((s) => (
                <SelectItem key={s} value={s} className="text-xs">
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Column manager placeholder */}
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" title="Gestionar columnas">
            <Columns3 className="h-3.5 w-3.5" /> Columnas
          </Button>

          {/* Clear filters */}
          {hasFilters && (
            <button
              type="button"
              className="flex h-8 items-center gap-1 rounded-md border border-dashed px-2.5 text-xs text-muted-foreground hover:bg-muted"
              onClick={clearFilters}
            >
              <X className="h-3 w-3" /> Limpiar
            </button>
          )}

          {/* Active filter badges */}
          {stage !== "all" && (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                stageChipCn(stage),
              )}
            >
              {stage}
              <button
                type="button"
                className="ml-0.5 opacity-60 hover:opacity-100"
                onClick={() => setStage("all")}
                aria-label="Quitar filtro de etapa"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          )}
        </div>
      </div>

      {/* ── Table ────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm">
          {/* Sticky thead */}
          <thead className="sticky top-0 z-10 border-b bg-muted/80 backdrop-blur">
            <tr>
              <th className="w-10 px-3 py-2.5 text-left">
                <input
                  type="checkbox"
                  aria-label="Seleccionar todos"
                  className="h-3.5 w-3.5 rounded border border-border accent-primary"
                />
              </th>
              {(
                [
                  { key: "name", label: "Cliente" },
                  { key: "phone", label: "Teléfono" },
                  { key: "stage", label: "Etapa" },
                  { key: "score", label: "Score" },
                  { key: "last_activity", label: "Última actividad" },
                  { key: "assigned", label: "Asignado a" },
                ] as const
              ).map(({ key, label }) => (
                <th
                  key={key}
                  className="py-2.5 pr-4 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  <button
                    type="button"
                    className="flex items-center gap-1 hover:text-foreground"
                    onClick={() => cycleSort(key)}
                  >
                    {label}
                    <ArrowUpDown
                      className={cn(
                        "h-3 w-3 transition-colors",
                        sortBy === key ? "text-foreground" : "text-muted-foreground/40",
                      )}
                    />
                  </button>
                </th>
              ))}
              {/* Actions header */}
              <th className="w-20 py-2.5 pr-3 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <span className="sr-only">Acciones</span>
              </th>
            </tr>
          </thead>

          <tbody>
            {query.isLoading ? (
              <SkeletonRows count={10} />
            ) : items.length === 0 ? (
              <EmptyState hasFilters={hasFilters} onClear={clearFilters} />
            ) : (
              items.map((c) => (
                <CustomerRow
                  key={c.id}
                  customer={c}
                  isHovered={hoveredId === c.id}
                  onHover={() => setHoveredId(c.id)}
                  onLeave={() => setHoveredId(null)}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ── Footer: pagination + shortcuts ───────────────────────────────── */}
      <div className="shrink-0 flex items-center justify-between border-t bg-card px-6 py-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-4">
          {[
            ["⌘K", "Buscar"],
            ["↑↓", "Navegar"],
            ["⌘↵", "Abrir detalle"],
            ["Esc", "Cerrar"],
          ].map(([key, label]) => (
            <span key={key} className="flex items-center gap-1">
              <kbd className="rounded border bg-background px-1 py-0.5 font-mono text-[9px] shadow-sm">
                {key}
              </kbd>
              {label}
            </span>
          ))}
        </div>

        <div className="flex items-center gap-4">
          {!query.isLoading && (
            <span>
              Mostrando 1–{Math.min(items.length, limit)} de {items.length}
            </span>
          )}

          {/* Page size */}
          <div className="flex items-center gap-1.5">
            <span>Por página:</span>
            <Select
              value={String(limit)}
              onValueChange={(v) => setLimit(Number(v) as (typeof PAGE_SIZES)[number])}
            >
              <SelectTrigger className="h-6 w-16 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZES.map((n) => (
                  <SelectItem key={n} value={String(n)} className="text-xs">
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Prev / next (visual only — real pagination via limit) */}
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-6 w-6 disabled:opacity-30" disabled>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <span className="min-w-[2rem] text-center">1</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 disabled:opacity-30"
              disabled={items.length < limit}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {/* ── ⌘K Command palette ───────────────────────────────────────────── */}
      <CommandDialog
        open={cmdOpen}
        onOpenChange={setCmdOpen}
        title="Buscar clientes"
        description="Busca por nombre o teléfono"
      >
        <CommandInput
          value={cmdQ}
          onValueChange={setCmdQ}
          placeholder="Nombre o teléfono…"
        />
        <CommandList className="max-h-80">
          <CommandEmpty>Sin resultados</CommandEmpty>
          <CommandGroup heading="Clientes">
            {cmdItems.map((c) => (
              <CommandItem
                key={c.id}
                value={`${c.name ?? ""} ${c.phone_e164}`}
                onSelect={() => {
                  setCmdOpen(false);
                  // Navigate programmatically via Link
                  window.location.href = `/customers/${c.id}`;
                }}
              >
                <Avatar className="mr-2 h-6 w-6">
                  <AvatarFallback className="text-[9px]">
                    {initials(c.name, c.phone_e164)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{c.name ?? "(sin nombre)"}</div>
                  <div className="text-xs text-muted-foreground">{c.phone_e164}</div>
                </div>
                {c.effective_stage && (
                  <Badge
                    variant="outline"
                    className={cn("ml-2 shrink-0 text-[10px]", stageChipCn(c.effective_stage))}
                  >
                    {c.effective_stage}
                  </Badge>
                )}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </div>
  );
}

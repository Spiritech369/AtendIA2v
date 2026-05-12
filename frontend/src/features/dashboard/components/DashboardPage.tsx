import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarCheck,
  CalendarDays,
  Clock,
  Copy,
  Eye,
  EyeOff,
  GripVertical,
  LayoutGrid,
  MessageSquare,
  Moon,
  MoreHorizontal,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  Sliders,
  Star,
  Sun,
  Trash2,
  TrendingDown,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { dashboardApi, type DashboardSummary } from "@/features/dashboard/api";
import { analyticsApi, type FunnelResponse, type VolumeBucket } from "@/features/analytics/api";
import { appointmentsApi, type AppointmentItem } from "@/features/appointments/api";
import { conversationsApi, type ConversationListItem } from "@/features/conversations/api";
import { customersApi, type CustomerListItem } from "@/features/customers/api";
import { workflowsApi, type WorkflowItem, type WorkflowExecution } from "@/features/workflows/api";
import { useAuthStore } from "@/stores/auth";

// ─── Types ────────────────────────────────────────────────────────────────────

type WidgetType =
  | "kpi_card"
  | "stale_conversations"
  | "upcoming_appointments"
  | "workflow_errors"
  | "high_score_leads"
  | "funnel"
  | "activity_heatmap";

interface WidgetConfig {
  id: string;
  type: WidgetType;
  title: string;
  description: string;
  icon: string;
  enabled: boolean;
  visible: boolean;
  order: number;
  size: "sm" | "md" | "lg";
  dataSource: string;
  refreshBehavior: "auto" | "manual" | "realtime";
  filters: Record<string, unknown>;
  thresholds: { warning?: number; critical?: number; goal?: number };
  actions: string[];
  emptyState: { title: string; hint: string; cta?: string };
  permissions: string[];
  createdAt: string;
  updatedAt: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "atendia_dash_v1";
const THEME_KEY = "atendia_theme";

const NOW_ISO = new Date().toISOString();

const DEFAULT_WIDGETS: WidgetConfig[] = [
  {
    id: "kpi-active",
    type: "kpi_card",
    title: "Conversaciones activas",
    description: "Conversaciones con actividad en las últimas 24 h",
    icon: "MessageSquare",
    enabled: true, visible: true, order: 0, size: "sm",
    dataSource: "dashboard.active_conversations",
    refreshBehavior: "realtime",
    filters: {},
    thresholds: { warning: 80, critical: 150 },
    actions: ["open_conversation"],
    emptyState: { title: "Sin conversaciones", hint: "Aún no hay mensajes entrantes.", cta: "Configurar WhatsApp" },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "kpi-appointments",
    type: "kpi_card",
    title: "Citas hoy",
    description: "Citas programadas para el día de hoy",
    icon: "CalendarCheck",
    enabled: true, visible: true, order: 1, size: "sm",
    dataSource: "dashboard.todays_appointments",
    refreshBehavior: "auto",
    filters: {},
    thresholds: { goal: 10 },
    actions: ["open_appointments"],
    emptyState: { title: "Sin citas hoy", hint: "No hay citas programadas para hoy." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "kpi-unattended",
    type: "kpi_card",
    title: "Leads sin atender > 1h",
    description: "Mensajes sin respuesta del operador por más de 1 hora",
    icon: "Clock",
    enabled: true, visible: true, order: 2, size: "sm",
    dataSource: "dashboard.unanswered_conversations",
    refreshBehavior: "realtime",
    filters: { min_age_hours: 1 },
    thresholds: { warning: 5, critical: 15 },
    actions: ["open_conversation"],
    emptyState: { title: "Todo al día", hint: "No hay leads sin responder. ¡Buen trabajo!" },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "kpi-response-rate",
    type: "kpi_card",
    title: "Tasa de respuesta",
    description: "Porcentaje de mensajes atendidos hoy vs total recibido",
    icon: "Zap",
    enabled: true, visible: true, order: 3, size: "sm",
    dataSource: "computed.response_rate",
    refreshBehavior: "auto",
    filters: {},
    thresholds: { warning: 80, critical: 60 },
    actions: [],
    emptyState: { title: "Sin datos", hint: "Disponible cuando haya conversaciones." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "stale-conv",
    type: "stale_conversations",
    title: "Conversaciones stale > 24h",
    description: "Conversaciones sin respuesta del operador por más de 24 h",
    icon: "AlertCircle",
    enabled: true, visible: true, order: 4, size: "md",
    dataSource: "conversations.list",
    refreshBehavior: "auto",
    filters: { min_age_hours: 24, limit: 5 },
    thresholds: { warning: 3, critical: 10 },
    actions: ["open_conversation"],
    emptyState: { title: "Sin conversaciones pendientes", hint: "Todos los clientes han recibido respuesta a tiempo." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "upcoming-appts",
    type: "upcoming_appointments",
    title: "Citas próximas 4h",
    description: "Citas agendadas en las próximas 4 horas",
    icon: "CalendarCheck",
    enabled: true, visible: true, order: 5, size: "md",
    dataSource: "appointments.list",
    refreshBehavior: "auto",
    filters: { window_hours: 4, limit: 5 },
    thresholds: { warning: 3 },
    actions: ["edit_appointment", "send_reminder"],
    emptyState: { title: "Sin citas próximas", hint: "No hay citas en las próximas 4 horas." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "workflow-errors",
    type: "workflow_errors",
    title: "Errores de workflow últimas 24h",
    description: "Ejecuciones fallidas de automatizaciones en el último día",
    icon: "AlertTriangle",
    enabled: true, visible: true, order: 6, size: "md",
    dataSource: "workflows.executions",
    refreshBehavior: "auto",
    filters: { status: "error", window_hours: 24, limit: 5 },
    thresholds: { warning: 1, critical: 5 },
    actions: ["view_execution"],
    emptyState: { title: "Sin errores recientes", hint: "Todas las automatizaciones funcionan correctamente." },
    permissions: ["tenant_admin"],
    createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "high-score-leads",
    type: "high_score_leads",
    title: "Leads de alto score sin asignar",
    description: "Clientes con mayor probabilidad de compra aún sin operador",
    icon: "Star",
    enabled: true, visible: true, order: 7, size: "md",
    dataSource: "customers.list",
    refreshBehavior: "auto",
    filters: { min_score: 80, limit: 5, unassigned: true },
    thresholds: { warning: 3 },
    actions: ["assign_lead"],
    emptyState: { title: "Sin leads de alto score", hint: "No hay leads con score alto sin asignar." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "funnel",
    type: "funnel",
    title: "Embudo de conversión",
    description: "Avance de oportunidades por etapa del pipeline",
    icon: "Activity",
    enabled: true, visible: true, order: 8, size: "lg",
    dataSource: "analytics.funnel",
    refreshBehavior: "manual",
    filters: {},
    thresholds: { goal: 50 },
    actions: ["view_report"],
    emptyState: { title: "Sin datos de embudo", hint: "Disponible cuando haya conversaciones procesadas." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
  {
    id: "heatmap",
    type: "activity_heatmap",
    title: "Mapa de actividad (últimos 7 días)",
    description: "Volumen de mensajes WhatsApp por día y hora de la semana",
    icon: "Activity",
    enabled: true, visible: true, order: 9, size: "lg",
    dataSource: "analytics.volume",
    refreshBehavior: "manual",
    filters: { metric: "inbound" },
    thresholds: {},
    actions: ["view_analysis"],
    emptyState: { title: "Sin datos de actividad", hint: "Disponible cuando haya mensajes procesados." },
    permissions: [], createdAt: NOW_ISO, updatedAt: NOW_ISO,
  },
];

const FUNNEL_STAGES: { key: keyof FunnelResponse; label: string; barCls: string }[] = [
  { key: "total_conversations", label: "Nuevos leads", barCls: "bg-blue-500" },
  { key: "quoted", label: "Cotizados", barCls: "bg-cyan-500" },
  { key: "plan_assigned", label: "Plan asignado", barCls: "bg-teal-500" },
  { key: "papeleria_completa", label: "Papelería completa", barCls: "bg-amber-500" },
];

const DAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

const CMD_NAV = [
  { label: "Dashboard", to: "/", shortcut: "D" },
  { label: "Bandeja de entrada", to: "/handoffs", shortcut: "C" },
  { label: "Leads", to: "/customers", shortcut: "L" },
  { label: "Pipeline", to: "/pipeline", shortcut: "P" },
  { label: "Citas", to: "/appointments", shortcut: "A" },
  { label: "Workflows", to: "/workflows", shortcut: undefined },
  { label: "Agentes IA", to: "/agents", shortcut: undefined },
  { label: "Configuración", to: "/config", shortcut: undefined },
  { label: "Analíticas", to: "/analytics", shortcut: undefined },
] as const;

// ─── Utilities ────────────────────────────────────────────────────────────────

function rel(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.round(diff / 60_000);
  if (m < 1) return "ahora";
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h`;
  const d = Math.round(h / 24);
  return `${d} d`;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
}

function sparkPath(vals: number[], w = 80, h = 28): string {
  if (vals.length < 2) return "";
  const max = Math.max(...vals);
  const min = Math.min(...vals);
  const range = max - min || 1;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `M ${pts.join(" L ")}`;
}

function pctDelta(vals: number[]): { pct: number; dir: "up" | "down" | "flat" } {
  const last = vals.at(-1) ?? 0;
  const prev = vals.at(-2) ?? 0;
  if (prev === 0) return { pct: 0, dir: "flat" };
  const pct = Math.round(((last - prev) / prev) * 100);
  if (pct === 0) return { pct: 0, dir: "flat" };
  return { pct: Math.abs(pct), dir: pct > 0 ? "up" : "down" };
}

function buildHeatMatrix(
  activityChart: DashboardSummary["activity_chart"],
  volumeBuckets: VolumeBucket[],
): { matrix: number[][]; maxVal: number } {
  const totalVol = volumeBuckets.reduce((s, b) => s + b.inbound + b.outbound, 0) || 1;
  const hourFrac: number[] = new Array(24).fill(1 / 24);
  volumeBuckets.forEach((b) => {
    if (b.hour >= 0 && b.hour < 24) {
      hourFrac[b.hour] = (b.inbound + b.outbound) / totalVol;
    }
  });

  const matrix: number[][] = Array.from({ length: 7 }, () => new Array(24).fill(0));
  activityChart.forEach((day) => {
    const js = new Date(day.date + "T12:00:00").getDay();
    const row = js === 0 ? 6 : js - 1;
    const total = day.inbound + day.outbound;
    for (let h = 0; h < 24; h++) {
      matrix[row]![h] = Math.round(total * (hourFrac[h] ?? 0));
    }
  });
  const maxVal = Math.max(...matrix.flat(), 1);
  return { matrix, maxVal };
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useTheme() {
  const [dark, setDark] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem(THEME_KEY);
      if (stored) return stored === "dark";
    } catch { /* ignore */ }
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) root.classList.add("dark");
    else root.classList.remove("dark");
    try { localStorage.setItem(THEME_KEY, dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);

  return { dark, toggle: () => setDark((d) => !d) };
}

function useWidgetConfig() {
  const [configs, setConfigs] = useState<WidgetConfig[]>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw) as WidgetConfig[];
    } catch { /* ignore */ }
    return DEFAULT_WIDGETS;
  });

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(configs)); } catch { /* ignore */ }
  }, [configs]);

  const update = useCallback((id: string, patch: Partial<WidgetConfig>) => {
    setConfigs((prev) =>
      prev.map((c) => (c.id === id ? { ...c, ...patch, updatedAt: new Date().toISOString() } : c)),
    );
  }, []);

  const reorder = useCallback((fromIdx: number, toIdx: number, group: WidgetType[]) => {
    setConfigs((prev) => {
      const inGroup = [...prev].filter((c) => group.includes(c.type)).sort((a, b) => a.order - b.order);
      const [moved] = inGroup.splice(fromIdx, 1);
      if (!moved) return prev;
      inGroup.splice(toIdx, 0, moved);
      const reindexed = new Map(inGroup.map((c, i) => [c.id, i]));
      return prev.map((c) => reindexed.has(c.id) ? { ...c, order: reindexed.get(c.id)! } : c);
    });
  }, []);

  const duplicate = useCallback((id: string) => {
    setConfigs((prev) => {
      const src = prev.find((c) => c.id === id);
      if (!src) return prev;
      const clone: WidgetConfig = { ...src, id: `${src.id}-copy-${Date.now()}`, title: `${src.title} (copia)`, order: prev.length, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
      return [...prev, clone];
    });
  }, []);

  const remove = useCallback((id: string) => {
    setConfigs((prev) => prev.filter((c) => c.id !== id));
  }, []);

  const reset = useCallback((id: string) => {
    const def = DEFAULT_WIDGETS.find((w) => w.id === id);
    if (def) setConfigs((prev) => prev.map((c) => (c.id === id ? { ...def } : c)));
  }, []);

  const resetAll = useCallback(() => setConfigs(DEFAULT_WIDGETS), []);

  const addWidget = useCallback((type: WidgetType) => {
    const def = DEFAULT_WIDGETS.find((w) => w.type === type);
    if (!def) return;
    const newW: WidgetConfig = { ...def, id: `${type}-${Date.now()}`, title: `${def.title} (nuevo)`, order: 999, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() };
    setConfigs((prev) => [...prev, newW]);
    toast.success("Widget añadido");
  }, []);

  return { configs, update, reorder, duplicate, remove, reset, resetAll, addWidget };
}

// ─── Primitives ───────────────────────────────────────────────────────────────

function Toggle({ checked, onCheckedChange, id }: { checked: boolean; onCheckedChange: (v: boolean) => void; id?: string }) {
  return (
    <button
      id={id}
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${checked ? "bg-primary" : "bg-muted"}`}
    >
      <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-background shadow-md transition-transform ${checked ? "translate-x-4" : "translate-x-0"}`} />
    </button>
  );
}

function Sparkline({ values, color = "currentColor", up = true }: { values: number[]; color?: string; up?: boolean }) {
  const path = sparkPath(values);
  if (!path) return <div className="h-7 w-20" />;
  return (
    <svg width={80} height={28} viewBox="0 0 80 28" fill="none" className="shrink-0">
      <path d={path} stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      <path d={`${path} L 80,28 L 0,28 Z`} fill={color} fillOpacity={0.08} />
    </svg>
  );
}

function WidgetEmptyState({ icon: Icon, title, hint, cta, to }: { icon: React.ComponentType<{ className?: string }>; title: string; hint: string; cta?: string; to?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-8 text-center">
      <Icon className="h-8 w-8 text-muted-foreground/50" />
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <p className="text-xs text-muted-foreground/70">{hint}</p>
      {cta && to && (
        <Link to={to} className="mt-1 text-xs text-primary hover:underline">{cta}</Link>
      )}
    </div>
  );
}

function WidgetHeader({ cfg, count, to, extra }: { cfg: WidgetConfig; count?: number; to?: string; extra?: React.ReactNode }) {
  return (
    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 pr-3">
      <div className="flex items-center gap-2">
        <CardTitle className="text-sm font-semibold">{cfg.title}</CardTitle>
        {count !== undefined && count > 0 && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px] tabular-nums">{count}</Badge>
        )}
      </div>
      <div className="flex items-center gap-1">
        {extra}
        {to && (
          <Link to={to} className="text-xs text-primary hover:underline">Ver todas</Link>
        )}
      </div>
    </CardHeader>
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

interface KpiCardProps {
  cfg: WidgetConfig;
  value: number | string;
  suffix?: string;
  sparkValues?: number[];
  deltaValues?: number[];
  subtitle?: string;
  accentCls: string;
  icon: React.ComponentType<{ className?: string }>;
  to?: string;
  isLoading?: boolean;
}

function KpiCard({ cfg, value, suffix = "", sparkValues = [], deltaValues = [], subtitle, accentCls, icon: Icon, to, isLoading }: KpiCardProps) {
  const { dir, pct } = pctDelta(deltaValues.length > 1 ? deltaValues : sparkValues);

  if (isLoading) {
    return (
      <Card className="rounded-2xl">
        <CardContent className="p-4">
          <Skeleton className="mb-3 h-3 w-28" />
          <Skeleton className="mb-2 h-8 w-16" />
          <Skeleton className="h-7 w-20" />
        </CardContent>
      </Card>
    );
  }

  const body = (
    <Card className={`rounded-2xl transition-shadow hover:shadow-md ${cfg.thresholds.critical !== undefined && typeof value === "number" && value >= cfg.thresholds.critical ? "border-destructive/40" : cfg.thresholds.warning !== undefined && typeof value === "number" && value >= cfg.thresholds.warning ? "border-amber-500/40" : ""}`}>
      <CardContent className="p-4">
        <div className="mb-1 flex items-center justify-between">
          <div className={`flex h-7 w-7 items-center justify-center rounded-md ${accentCls}`}>
            <Icon className="h-4 w-4" />
          </div>
          {sparkValues.length > 1 && (
            <Sparkline values={sparkValues} color={dir === "up" ? "#22c55e" : dir === "down" ? "#ef4444" : "currentColor"} />
          )}
        </div>
        <div className="mt-2 text-2xl font-bold tabular-nums leading-none tracking-tight">
          {value}{suffix}
        </div>
        <div className="mt-1 flex items-center gap-1.5">
          {dir !== "flat" && pct > 0 ? (
            <span className={`flex items-center gap-0.5 text-xs font-medium ${dir === "up" ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
              {dir === "up" ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {pct}%
            </span>
          ) : null}
          <span className="text-xs text-muted-foreground">
            {subtitle ?? "vs ayer"}
          </span>
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">{cfg.title}</p>
      </CardContent>
    </Card>
  );

  if (to) return <Link to={to} className="block">{body}</Link>;
  return body;
}

// ─── Stale Conversations Widget ────────────────────────────────────────────────

function StaleConversationsWidget({ cfg, items, isLoading }: { cfg: WidgetConfig; items: ConversationListItem[]; isLoading: boolean }) {
  const maxRows = (cfg.filters.limit as number | undefined) ?? 5;
  const minAgeHours = (cfg.filters.min_age_hours as number | undefined) ?? 24;
  const stale = items
    .filter((c) => Date.now() - new Date(c.last_activity_at).getTime() > minAgeHours * 60 * 60_000)
    .slice(0, maxRows);

  return (
    <Card className="rounded-2xl">
      <WidgetHeader cfg={cfg} count={stale.length} to="/conversations" />
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-2">{[0,1,2,3,4].map((i) => <Skeleton key={i} className="h-9 w-full rounded-md" />)}</div>
        ) : stale.length === 0 ? (
          <WidgetEmptyState icon={AlertCircle} title={cfg.emptyState.title} hint={cfg.emptyState.hint} />
        ) : (
          <div className="space-y-1">
            {stale.map((c) => (
              <div key={c.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs">
                <div className="h-6 w-6 shrink-0 rounded-full bg-muted flex items-center justify-center text-[10px] font-semibold text-muted-foreground">
                  {(c.customer_name ?? c.customer_phone).charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{c.customer_name ?? c.customer_phone}</div>
                  <div className="truncate text-muted-foreground">{c.customer_phone}</div>
                </div>
                <span className="shrink-0 tabular-nums text-muted-foreground">{rel(c.last_activity_at)}</span>
                <Link to="/conversations/$conversationId" params={{ conversationId: c.id }}>
                  <Button variant="outline" size="sm" className="h-6 px-2 text-xs">Abrir</Button>
                </Link>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Upcoming Appointments Widget ─────────────────────────────────────────────

function UpcomingAppointmentsWidget({ cfg, items, isLoading }: { cfg: WidgetConfig; items: AppointmentItem[]; isLoading: boolean }) {
  const maxRows = (cfg.filters.limit as number | undefined) ?? 5;
  const rows = items.slice(0, maxRows);

  return (
    <Card className="rounded-2xl">
      <WidgetHeader cfg={cfg} count={rows.length} to="/appointments" />
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-2">{[0,1,2,3,4].map((i) => <Skeleton key={i} className="h-9 w-full rounded-md" />)}</div>
        ) : rows.length === 0 ? (
          <WidgetEmptyState icon={CalendarCheck} title={cfg.emptyState.title} hint={cfg.emptyState.hint} />
        ) : (
          <div className="space-y-1">
            {rows.map((a) => (
              <div key={a.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs">
                <span className="shrink-0 tabular-nums font-medium text-muted-foreground w-9">{fmtTime(a.scheduled_at)}</span>
                <div className="h-6 w-6 shrink-0 rounded-full bg-muted flex items-center justify-center text-[10px] font-semibold text-muted-foreground">
                  {(a.customer_name ?? a.customer_phone).charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{a.customer_name ?? a.customer_phone}</div>
                  <div className="truncate text-muted-foreground">{a.service}</div>
                </div>
                <Button variant="outline" size="sm" className="h-6 px-2 text-xs shrink-0">Editar</Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Workflow Errors Widget ────────────────────────────────────────────────────

function WorkflowErrorsWidget({ cfg }: { cfg: WidgetConfig }) {
  const maxRows = (cfg.filters.limit as number | undefined) ?? 5;
  const wfQuery = useQuery({ queryKey: ["workflows"], queryFn: workflowsApi.list, staleTime: 60_000 });
  const wfList = wfQuery.data ?? [];
  const first5 = wfList.slice(0, 5);

  const execQueries = useQueries({
    queries: first5.map((w) => ({
      queryKey: ["workflows", w.id, "executions"] as const,
      queryFn: () => workflowsApi.executions(w.id),
      enabled: wfQuery.isSuccess,
      staleTime: 60_000,
    })),
  });

  const errors = (() => {
    const cutoff = Date.now() - 24 * 60 * 60_000;
    return execQueries
      .flatMap((q, i) => {
        if (!q.data) return [];
        const wf = first5[i];
        if (!wf) return [];
        return q.data
          .filter((e) => e.status === "error" && e.error !== null && new Date(e.started_at).getTime() > cutoff)
          .map((e) => ({ wfName: wf.name, error: e.error!, startedAt: e.started_at, wfId: wf.id }));
      })
      .sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())
      .slice(0, maxRows);
  })();

  const isLoading = wfQuery.isLoading || execQueries.some((q) => q.isLoading);

  return (
    <Card className="rounded-2xl">
      <WidgetHeader cfg={cfg} count={errors.length} to="/workflows" />
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-2">{[0,1,2,3,4].map((i) => <Skeleton key={i} className="h-9 w-full rounded-md" />)}</div>
        ) : errors.length === 0 ? (
          <WidgetEmptyState icon={AlertTriangle} title={cfg.emptyState.title} hint={cfg.emptyState.hint} />
        ) : (
          <div className="space-y-1">
            {errors.map((e, i) => (
              <div key={i} className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/5 px-2.5 py-1.5 text-xs">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-destructive/90">{e.error}</div>
                  <div className="truncate text-muted-foreground">{e.wfName}</div>
                </div>
                <span className="shrink-0 tabular-nums text-muted-foreground">{rel(e.startedAt)}</span>
                <Link to="/workflows">
                  <Button variant="outline" size="sm" className="h-6 px-2 text-xs shrink-0">Ver</Button>
                </Link>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── High-Score Leads Widget ──────────────────────────────────────────────────

function HighScoreLeadsWidget({ cfg, items, isLoading }: { cfg: WidgetConfig; items: CustomerListItem[]; isLoading: boolean }) {
  const maxRows = (cfg.filters.limit as number | undefined) ?? 5;
  const minScore = (cfg.filters.min_score as number | undefined) ?? 80;
  const rows = items.filter((c) => c.score >= minScore && c.assigned_user_email === null).slice(0, maxRows);

  const scoreCls = (s: number) =>
    s >= 90 ? "bg-green-500/15 text-green-700 dark:text-green-300" :
    s >= 80 ? "bg-amber-500/15 text-amber-700 dark:text-amber-300" :
    "bg-muted text-muted-foreground";

  return (
    <Card className="rounded-2xl">
      <WidgetHeader cfg={cfg} count={rows.length} to="/customers" />
      <CardContent className="pt-0">
        {isLoading ? (
          <div className="space-y-2">{[0,1,2,3,4].map((i) => <Skeleton key={i} className="h-9 w-full rounded-md" />)}</div>
        ) : rows.length === 0 ? (
          <WidgetEmptyState icon={Star} title={cfg.emptyState.title} hint={cfg.emptyState.hint} />
        ) : (
          <div className="space-y-1">
            {rows.map((c) => (
              <div key={c.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs">
                <span className={`shrink-0 w-7 rounded px-1 py-0.5 text-center text-[10px] font-bold tabular-nums ${scoreCls(c.score)}`}>{c.score}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{c.name ?? c.phone_e164}</div>
                  <div className="truncate text-muted-foreground">{c.phone_e164}</div>
                </div>
                <Link to="/customers/$customerId" params={{ customerId: c.id }}>
                  <Button variant="outline" size="sm" className="h-6 px-2 text-xs shrink-0">Asignar</Button>
                </Link>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Funnel Widget ────────────────────────────────────────────────────────────

function FunnelWidget({ cfg, data, isLoading }: { cfg: WidgetConfig; data: FunnelResponse | undefined; isLoading: boolean }) {
  const maxVal = data ? Math.max(data.total_conversations, 1) : 1;

  if (isLoading || !data) {
    return (
      <Card className="rounded-2xl">
        <WidgetHeader cfg={cfg} />
        <CardContent className="space-y-3 pt-2">
          {[0,1,2,3].map((i) => <Skeleton key={i} className="h-8 w-full rounded" />)}
        </CardContent>
      </Card>
    );
  }

  const hasData = data.total_conversations > 0;

  return (
    <Card className="rounded-2xl">
      <WidgetHeader cfg={cfg} extra={
        <Link to="/analytics" className="text-xs text-primary hover:underline mr-2">Ver reporte completo</Link>
      } />
      <CardContent className="pt-1">
        {!hasData ? (
          <WidgetEmptyState icon={Activity} title={cfg.emptyState.title} hint={cfg.emptyState.hint} />
        ) : (
          <div className="space-y-2">
            {FUNNEL_STAGES.map((stage, i) => {
              const val = data[stage.key] as number;
              const next = i < FUNNEL_STAGES.length - 1 ? data[FUNNEL_STAGES[i + 1]!.key] as number : null;
              const conv = next !== null && val > 0 ? Math.round((next / val) * 100) : null;
              const width = Math.round((val / maxVal) * 100);
              return (
                <div key={stage.key} className="flex items-center gap-3">
                  <span className="w-32 shrink-0 truncate text-xs text-muted-foreground">{stage.label}</span>
                  <div className="flex flex-1 items-center gap-2">
                    <div className="h-6 flex-1 overflow-hidden rounded bg-muted">
                      <div
                        className={`h-full ${stage.barCls} transition-all duration-700`}
                        style={{ width: `${width}%` }}
                      />
                    </div>
                    <span className="w-16 shrink-0 text-right text-xs font-semibold tabular-nums">{val.toLocaleString("es-MX")}</span>
                    {conv !== null ? (
                      <span className="w-10 shrink-0 text-right text-xs text-muted-foreground">{conv}%</span>
                    ) : <span className="w-10" />}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Heatmap Widget ───────────────────────────────────────────────────────────

function HeatmapWidget({ cfg, activityChart, volumeBuckets, isLoading }: {
  cfg: WidgetConfig;
  activityChart: DashboardSummary["activity_chart"];
  volumeBuckets: VolumeBucket[];
  isLoading: boolean;
}) {
  const { matrix, maxVal } = useMemo(
    () => buildHeatMatrix(activityChart, volumeBuckets),
    [activityChart, volumeBuckets],
  );

  const hasData = activityChart.some((d) => d.inbound + d.outbound > 0);
  const DISPLAY_HOURS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22];

  if (isLoading) {
    return (
      <Card className="rounded-2xl">
        <WidgetHeader cfg={cfg} />
        <CardContent>
          <Skeleton className="h-40 w-full rounded" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="rounded-2xl">
      <WidgetHeader cfg={cfg} extra={
        <Link to="/analytics" className="text-xs text-primary hover:underline mr-2">Ver análisis completo</Link>
      } />
      <CardContent className="pt-1">
        {!hasData ? (
          <WidgetEmptyState icon={Activity} title={cfg.emptyState.title} hint={cfg.emptyState.hint} />
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[480px]">
              {/* Hour labels */}
              <div className="mb-1 flex items-center">
                <span className="w-8 shrink-0" />
                <div className="flex flex-1 justify-between">
                  {DISPLAY_HOURS.map((h) => (
                    <span key={h} className="text-center text-[9px] text-muted-foreground w-4">{String(h).padStart(2, "0")}</span>
                  ))}
                </div>
              </div>
              {/* Grid rows */}
              {DAYS_ES.map((day, di) => (
                <div key={day} className="mb-1 flex items-center gap-1">
                  <span className="w-7 shrink-0 text-[10px] text-muted-foreground">{day}</span>
                  <div className="flex flex-1 gap-0.5">
                    {Array.from({ length: 24 }, (_, h) => {
                      const val = matrix[di]?.[h] ?? 0;
                      const intensity = val / maxVal;
                      return (
                        <TooltipProvider key={h} delayDuration={0}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <div
                                className="h-3.5 flex-1 rounded-[2px] transition-opacity"
                                style={{ opacity: 0.1 + intensity * 0.9, backgroundColor: "var(--color-primary, hsl(221 83% 53%))" }}
                              />
                            </TooltipTrigger>
                            <TooltipContent side="top" className="text-xs">
                              {day} {String(h).padStart(2, "0")}:00 · {val} msgs
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      );
                    })}
                  </div>
                </div>
              ))}
              {/* Legend */}
              <div className="mt-2 flex items-center justify-end gap-2">
                <span className="text-[10px] text-muted-foreground">Menos</span>
                {[0.1, 0.3, 0.5, 0.7, 0.9].map((op) => (
                  <div key={op} className="h-3 w-3 rounded-[2px]" style={{ opacity: op, backgroundColor: "var(--color-primary, hsl(221 83% 53%))" }} />
                ))}
                <span className="text-[10px] text-muted-foreground">Más mensajes</span>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Settings Dialog ──────────────────────────────────────────────────────────

function SettingsDialog({ open, onClose, configs, wc }: {
  open: boolean;
  onClose: () => void;
  configs: WidgetConfig[];
  wc: ReturnType<typeof useWidgetConfig>;
}) {
  const [editId, setEditId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<WidgetConfig | null>(null);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  const sorted = [...configs].sort((a, b) => a.order - b.order);
  const kpiWidgets = sorted.filter((c) => c.type === "kpi_card");
  const listWidgets = sorted.filter((c) => ["stale_conversations", "upcoming_appointments", "workflow_errors", "high_score_leads"].includes(c.type));
  const chartWidgets = sorted.filter((c) => ["funnel", "activity_heatmap"].includes(c.type));

  const startEdit = (cfg: WidgetConfig) => { setEditId(cfg.id); setEditDraft({ ...cfg }); };
  const saveEdit = () => {
    if (!editDraft) return;
    wc.update(editDraft.id, editDraft);
    setEditId(null);
    setEditDraft(null);
    toast.success("Widget actualizado");
  };
  const cancelEdit = () => { setEditId(null); setEditDraft(null); };

  const WIDGET_TYPE_OPTIONS: WidgetType[] = ["kpi_card", "stale_conversations", "upcoming_appointments", "workflow_errors", "high_score_leads", "funnel", "activity_heatmap"];

  function DraggableList({ items, group }: { items: WidgetConfig[]; group: WidgetType[] }) {
    return (
      <div className="space-y-1">
        {items.map((cfg, i) => (
          <div
            key={cfg.id}
            draggable
            onDragStart={() => setDragIdx(i)}
            onDragOver={(e) => { e.preventDefault(); setDragOverIdx(i); }}
            onDrop={() => { if (dragIdx !== null) wc.reorder(dragIdx, i, group); setDragIdx(null); setDragOverIdx(null); }}
            onDragEnd={() => { setDragIdx(null); setDragOverIdx(null); }}
            className={`flex items-center gap-2 rounded-md border px-2.5 py-2 text-xs transition-colors cursor-grab active:cursor-grabbing ${dragOverIdx === i ? "border-primary bg-primary/5" : "bg-card"}`}
          >
            <GripVertical className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="flex-1 truncate font-medium">{cfg.title}</span>
            <Badge variant="outline" className="text-[10px] capitalize shrink-0">{cfg.size}</Badge>
            <Toggle checked={cfg.visible} onCheckedChange={(v) => wc.update(cfg.id, { visible: v })} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col p-0">
        <DialogHeader className="px-6 pt-5 pb-0">
          <DialogTitle className="text-base">Configuración del Dashboard</DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            Personaliza widgets, umbrales, acciones y apariencia del dashboard.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="layout" className="flex flex-1 flex-col overflow-hidden">
          <TabsList className="mx-6 mt-3 justify-start gap-0.5 h-8 bg-muted/50">
            <TabsTrigger value="layout" className="h-7 text-xs gap-1"><LayoutGrid className="h-3 w-3" />Layout</TabsTrigger>
            <TabsTrigger value="widgets" className="h-7 text-xs gap-1"><Settings2 className="h-3 w-3" />Widgets</TabsTrigger>
            <TabsTrigger value="rules" className="h-7 text-xs gap-1"><Sliders className="h-3 w-3" />Reglas</TabsTrigger>
            <TabsTrigger value="actions" className="h-7 text-xs gap-1"><Zap className="h-3 w-3" />Acciones</TabsTrigger>
            <TabsTrigger value="display" className="h-7 text-xs gap-1"><Eye className="h-3 w-3" />Visualización</TabsTrigger>
          </TabsList>

          <ScrollArea className="flex-1 px-6 pb-4 mt-3">
            {/* Layout Tab */}
            <TabsContent value="layout" className="mt-0 space-y-4">
              <div>
                <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">KPI Cards</p>
                <DraggableList items={kpiWidgets} group={["kpi_card"]} />
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Listas de atención</p>
                <DraggableList items={listWidgets} group={["stale_conversations", "upcoming_appointments", "workflow_errors", "high_score_leads"]} />
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold text-muted-foreground uppercase tracking-wide">Gráficas</p>
                <DraggableList items={chartWidgets} group={["funnel", "activity_heatmap"]} />
              </div>
              <div className="flex justify-end">
                <Button variant="outline" size="sm" className="text-xs gap-1.5" onClick={() => { wc.resetAll(); toast.success("Layout restaurado"); }}>
                  <RotateCcw className="h-3.5 w-3.5" />Restaurar layout por defecto
                </Button>
              </div>
            </TabsContent>

            {/* Widgets Tab */}
            <TabsContent value="widgets" className="mt-0 space-y-3">
              {editId && editDraft ? (
                <div className="rounded-lg border p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold">Editando widget</p>
                    <div className="flex gap-1.5">
                      <Button variant="outline" size="sm" className="text-xs h-7" onClick={cancelEdit}>Cancelar</Button>
                      <Button size="sm" className="text-xs h-7" onClick={saveEdit}>Guardar</Button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs">Título</Label>
                      <Input value={editDraft.title} onChange={(e) => setEditDraft({ ...editDraft, title: e.target.value })} className="h-7 text-xs" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Tamaño</Label>
                      <Select value={editDraft.size} onValueChange={(v) => setEditDraft({ ...editDraft, size: v as WidgetConfig["size"] })}>
                        <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="sm">Pequeño (sm)</SelectItem>
                          <SelectItem value="md">Mediano (md)</SelectItem>
                          <SelectItem value="lg">Grande (lg)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Actualización</Label>
                      <Select value={editDraft.refreshBehavior} onValueChange={(v) => setEditDraft({ ...editDraft, refreshBehavior: v as WidgetConfig["refreshBehavior"] })}>
                        <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="auto">Automática</SelectItem>
                          <SelectItem value="manual">Manual</SelectItem>
                          <SelectItem value="realtime">Tiempo real</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1 col-span-2">
                      <Label className="text-xs">Descripción</Label>
                      <Input value={editDraft.description} onChange={(e) => setEditDraft({ ...editDraft, description: e.target.value })} className="h-7 text-xs" />
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                      <Toggle id="edit-enabled" checked={editDraft.enabled} onCheckedChange={(v) => setEditDraft({ ...editDraft, enabled: v })} />
                      <Label htmlFor="edit-enabled" className="text-xs cursor-pointer">Habilitado</Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <Toggle id="edit-visible" checked={editDraft.visible} onCheckedChange={(v) => setEditDraft({ ...editDraft, visible: v })} />
                      <Label htmlFor="edit-visible" className="text-xs cursor-pointer">Visible</Label>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">Haz clic en ••• para editar, duplicar o eliminar un widget.</p>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="text-xs gap-1.5 h-7"><Plus className="h-3.5 w-3.5" />Añadir widget</Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {WIDGET_TYPE_OPTIONS.map((t) => (
                          <DropdownMenuItem key={t} className="text-xs" onClick={() => wc.addWidget(t)}>
                            {t.replace(/_/g, " ")}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <div className="space-y-1">
                    {sorted.map((cfg) => (
                      <div key={cfg.id} className="flex items-center gap-2 rounded-md border px-3 py-2 text-xs">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium truncate">{cfg.title}</span>
                            {!cfg.enabled && <Badge variant="secondary" className="text-[10px]">Deshabilitado</Badge>}
                            {!cfg.visible && <Badge variant="outline" className="text-[10px]">Oculto</Badge>}
                          </div>
                          <p className="truncate text-muted-foreground text-[10px]">{cfg.description}</p>
                        </div>
                        <Toggle checked={cfg.enabled} onCheckedChange={(v) => { wc.update(cfg.id, { enabled: v }); toast.success(v ? "Widget habilitado" : "Widget deshabilitado"); }} />
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-6 w-6 p-0" title="Más opciones"><MoreHorizontal className="h-3.5 w-3.5" /></Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="text-xs">
                            <DropdownMenuItem className="text-xs" onClick={() => startEdit(cfg)}>Editar</DropdownMenuItem>
                            <DropdownMenuItem className="text-xs" onClick={() => { wc.duplicate(cfg.id); toast.success("Widget duplicado"); }}>Duplicar</DropdownMenuItem>
                            <DropdownMenuItem className="text-xs" onClick={() => { wc.update(cfg.id, { visible: !cfg.visible }); }}>
                              {cfg.visible ? "Ocultar" : "Mostrar"}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="text-xs" onClick={() => { wc.reset(cfg.id); toast.success("Widget restaurado"); }}>Restaurar defaults</DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem className="text-xs text-destructive" onClick={() => { wc.remove(cfg.id); toast.success("Widget eliminado"); }}>Eliminar</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </TabsContent>

            {/* Rules Tab */}
            <TabsContent value="rules" className="mt-0 space-y-4">
              <p className="text-xs text-muted-foreground">Configura los umbrales que determinan cuando un widget cambia su estado visual.</p>
              {sorted.map((cfg) => (
                cfg.thresholds.warning !== undefined || cfg.thresholds.critical !== undefined || cfg.thresholds.goal !== undefined ? (
                  <div key={cfg.id} className="rounded-lg border p-3 space-y-2">
                    <p className="text-xs font-semibold">{cfg.title}</p>
                    <div className="grid grid-cols-3 gap-3">
                      {cfg.thresholds.warning !== undefined && (
                        <div className="space-y-1">
                          <Label className="text-[10px] text-amber-600 dark:text-amber-400 font-semibold">Advertencia</Label>
                          <Input
                            type="number"
                            defaultValue={cfg.thresholds.warning}
                            className="h-7 text-xs"
                            onBlur={(e) => wc.update(cfg.id, { thresholds: { ...cfg.thresholds, warning: Number(e.target.value) } })}
                          />
                        </div>
                      )}
                      {cfg.thresholds.critical !== undefined && (
                        <div className="space-y-1">
                          <Label className="text-[10px] text-destructive font-semibold">Crítico</Label>
                          <Input
                            type="number"
                            defaultValue={cfg.thresholds.critical}
                            className="h-7 text-xs"
                            onBlur={(e) => wc.update(cfg.id, { thresholds: { ...cfg.thresholds, critical: Number(e.target.value) } })}
                          />
                        </div>
                      )}
                      {cfg.thresholds.goal !== undefined && (
                        <div className="space-y-1">
                          <Label className="text-[10px] text-green-600 dark:text-green-400 font-semibold">Meta</Label>
                          <Input
                            type="number"
                            defaultValue={cfg.thresholds.goal}
                            className="h-7 text-xs"
                            onBlur={(e) => wc.update(cfg.id, { thresholds: { ...cfg.thresholds, goal: Number(e.target.value) } })}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                ) : null
              ))}
            </TabsContent>

            {/* Actions Tab */}
            <TabsContent value="actions" className="mt-0 space-y-4">
              <p className="text-xs text-muted-foreground">Configura qué acciones aparecen en cada widget y cómo se abren.</p>
              {sorted.map((cfg) => cfg.actions.length > 0 && (
                <div key={cfg.id} className="rounded-lg border p-3 space-y-2">
                  <p className="text-xs font-semibold">{cfg.title}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {cfg.actions.map((action) => (
                      <Badge key={action} variant="secondary" className="text-[10px] gap-1 cursor-default">
                        <Zap className="h-2.5 w-2.5" />{action.replace(/_/g, " ")}
                      </Badge>
                    ))}
                  </div>
                  <div className="flex items-center gap-2">
                    <Label className="text-[10px] text-muted-foreground">Abrir en:</Label>
                    <Select defaultValue="route">
                      <SelectTrigger className="h-6 text-xs w-28"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="route">Ruta</SelectItem>
                        <SelectItem value="modal">Modal</SelectItem>
                        <SelectItem value="drawer">Drawer</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              ))}
            </TabsContent>

            {/* Display Tab */}
            <TabsContent value="display" className="mt-0 space-y-4">
              <div className="rounded-lg border p-3 space-y-3">
                <p className="text-xs font-semibold">Densidad</p>
                <div className="flex gap-2">
                  {["Compacto", "Cómodo"].map((d) => (
                    <button key={d} className="flex-1 rounded-md border px-3 py-2 text-xs hover:border-primary transition-colors first:border-primary first:text-primary">{d}</button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-semibold">Estados vacíos personalizados</p>
                {sorted.map((cfg) => (
                  <div key={cfg.id} className="rounded-lg border p-3 space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">{cfg.title}</p>
                    <div className="grid gap-2">
                      <div className="space-y-1">
                        <Label className="text-[10px]">Título del estado vacío</Label>
                        <Input
                          defaultValue={cfg.emptyState.title}
                          className="h-7 text-xs"
                          onBlur={(e) => wc.update(cfg.id, { emptyState: { ...cfg.emptyState, title: e.target.value } })}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[10px]">Hint</Label>
                        <Input
                          defaultValue={cfg.emptyState.hint}
                          className="h-7 text-xs"
                          onBlur={(e) => wc.update(cfg.id, { emptyState: { ...cfg.emptyState, hint: e.target.value } })}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </TabsContent>
          </ScrollArea>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ─── Command Palette ──────────────────────────────────────────────────────────

function CmdPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <CommandDialog open={open} onOpenChange={(o) => !o && onClose()} title="Paleta de comandos" description="Busca páginas y acciones rápidas">
      <CommandInput placeholder="Buscar página o acción…" />
      <CommandList>
        <CommandEmpty>Sin resultados.</CommandEmpty>
        <CommandGroup heading="Navegación">
          {CMD_NAV.map((item) => (
            <CommandItem key={item.to} onSelect={onClose} asChild>
              <Link to={item.to} className="flex w-full items-center">
                {item.label}
                {item.shortcut && <CommandShortcut>⌘{item.shortcut}</CommandShortcut>}
              </Link>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Acciones rápidas">
          <CommandItem onSelect={() => { toast.info("Feature en construcción", { description: '"Nueva conversación" estará disponible próximamente.' }); onClose(); }}>Nueva conversación</CommandItem>
          <CommandItem onSelect={() => { toast.info("Feature en construcción", { description: '"Crear cita" estará disponible próximamente.' }); onClose(); }}>Crear cita</CommandItem>
          <CommandItem onSelect={() => { toast.info("Feature en construcción", { description: '"Exportar clientes" estará disponible próximamente.' }); onClose(); }}>Exportar clientes</CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

// ─── DashboardPage ────────────────────────────────────────────────────────────

export function DashboardPage() {
  const me = useAuthStore((s) => s.user);
  const qc = useQueryClient();
  const { dark, toggle: toggleTheme } = useTheme();
  const wc = useWidgetConfig();
  const { configs } = wc;

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(() => new Date());
  const [refreshing, setRefreshing] = useState(false);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setCmdOpen(true); }
      if (e.key === "Escape") { setSettingsOpen(false); setCmdOpen(false); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Date range for queries
  const now4h = useMemo(() => {
    const from = new Date();
    const to = new Date(from.getTime() + 4 * 60 * 60_000);
    return { from: from.toISOString(), to: to.toISOString() };
  }, []);

  const last7 = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - 7 * 24 * 60 * 60_000);
    return { from: from.toISOString().split("T")[0]!, to: to.toISOString().split("T")[0]! };
  }, []);

  // Queries
  const dashQ = useQuery({ queryKey: ["dashboard"], queryFn: dashboardApi.summary, refetchInterval: 60_000 });
  const funnelQ = useQuery({ queryKey: ["analytics", "funnel"], queryFn: () => analyticsApi.funnel(last7), staleTime: 5 * 60_000 });
  const volumeQ = useQuery({ queryKey: ["analytics", "volume"], queryFn: () => analyticsApi.volume(last7), staleTime: 5 * 60_000 });
  const convQ = useQuery({ queryKey: ["conversations", { limit: 20, status: "active" }], queryFn: () => conversationsApi.list({ limit: 20, status: "active" }), refetchInterval: 60_000 });
  const apptQ = useQuery({ queryKey: ["appointments", "next4h"], queryFn: () => appointmentsApi.list({ date_from: now4h.from, date_to: now4h.to, status: "scheduled", limit: 5 }), refetchInterval: 60_000 });
  const leadsQ = useQuery({ queryKey: ["customers", { sort_by: "score", sort_dir: "desc", limit: 10 }], queryFn: () => customersApi.list({ sort_by: "score", sort_dir: "desc", limit: 10 }), refetchInterval: 120_000 });

  const dash = dashQ.data;
  const activityChart = dash?.activity_chart ?? [];
  const volumeBuckets = volumeQ.data?.buckets ?? [];

  // KPI computations
  const sparkActive = activityChart.map((d) => d.inbound);
  const sparkRate = activityChart.map((d) => Math.round(d.outbound / Math.max(d.inbound, 1) * 100));
  const sparkUnattended = activityChart.map((d) => Math.max(d.inbound - d.outbound, 0));
  const responseRate = dash ? Math.round((1 - dash.unanswered_conversations / Math.max(dash.conversations_today, 1)) * 100) : 0;

  // Sorted & filtered widget configs
  const kpiCfgs = configs.filter((c) => c.type === "kpi_card" && c.visible && c.enabled).sort((a, b) => a.order - b.order);
  const listCfgs = configs.filter((c) => ["stale_conversations", "upcoming_appointments", "workflow_errors", "high_score_leads"].includes(c.type) && c.visible && c.enabled).sort((a, b) => a.order - b.order);
  const chartCfgs = configs.filter((c) => ["funnel", "activity_heatmap"].includes(c.type) && c.visible && c.enabled).sort((a, b) => a.order - b.order);

  // KPI data map
  const kpiData: Record<string, { value: number | string; suffix?: string; spark?: number[]; icon: React.ComponentType<{ className?: string }>; accentCls: string; to?: string }> = {
    "kpi-active": { value: dash?.active_conversations ?? 0, spark: sparkActive, icon: MessageSquare, accentCls: "bg-blue-500/15 text-blue-600 dark:text-blue-300", to: "/conversations" },
    "kpi-appointments": { value: dash?.todays_appointments.length ?? 0, icon: CalendarCheck, accentCls: "bg-violet-500/15 text-violet-600 dark:text-violet-300", to: "/appointments" },
    "kpi-unattended": { value: dash?.unanswered_conversations ?? 0, spark: sparkUnattended, icon: Clock, accentCls: "bg-amber-500/15 text-amber-600 dark:text-amber-300" },
    "kpi-response-rate": { value: responseRate, suffix: "%", spark: sparkRate, icon: Zap, accentCls: "bg-green-500/15 text-green-600 dark:text-green-300" },
  };

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["dashboard"] }),
        qc.invalidateQueries({ queryKey: ["analytics"] }),
        qc.invalidateQueries({ queryKey: ["conversations"] }),
        qc.invalidateQueries({ queryKey: ["appointments"] }),
        qc.invalidateQueries({ queryKey: ["customers"] }),
      ]);
      setLastRefresh(new Date());
      toast.success("Dashboard actualizado");
    } catch {
      toast.error("Error al actualizar");
    } finally {
      setRefreshing(false);
    }
  }, [qc]);

  const relLastRefresh = (() => {
    const diff = Date.now() - lastRefresh.getTime();
    const m = Math.round(diff / 60_000);
    if (m < 1) return "hace 1 min";
    return `hace ${m} min`;
  })();

  return (
    <TooltipProvider>
      <div className="space-y-4">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold tracking-tight">Dashboard</h1>
            <p className="text-xs text-muted-foreground">
              Resumen de hoy ·{" "}
              {new Date().toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" })}
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            {/* Theme toggle */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={toggleTheme} title={dark ? "Modo claro" : "Modo oscuro"}>
                  {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">{dark ? "Modo claro" : "Modo oscuro"}</TooltipContent>
            </Tooltip>
            {/* Command palette */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => setCmdOpen(true)} title="Paleta de comandos (Ctrl+K)">
                  <Search className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">Paleta de comandos <kbd className="ml-1 rounded border px-1 font-mono text-[10px]">⌘K</kbd></TooltipContent>
            </Tooltip>
            {/* Settings */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => setSettingsOpen(true)} title="Configuración del dashboard">
                  <Settings2 className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">Configuración del dashboard</TooltipContent>
            </Tooltip>
            {/* Refresh */}
            <div className="flex items-center gap-2 rounded-md border px-2.5 py-1">
              <Button variant="ghost" size="sm" className="h-6 gap-1.5 px-1.5 text-xs" onClick={handleRefresh} disabled={refreshing}>
                <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
                Actualizar
              </Button>
              <Separator orientation="vertical" className="h-4" />
              <div className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
                <span className="text-[10px] text-muted-foreground">{relLastRefresh}</span>
              </div>
            </div>
          </div>
        </div>

        {/* KPI Cards */}
        {kpiCfgs.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {kpiCfgs.map((cfg) => {
              const d = kpiData[cfg.id];
              return (
                <KpiCard
                  key={cfg.id}
                  cfg={cfg}
                  value={d?.value ?? 0}
                  suffix={d?.suffix}
                  sparkValues={d?.spark ?? []}
                  deltaValues={d?.spark ?? []}
                  icon={d?.icon ?? Activity}
                  accentCls={d?.accentCls ?? "bg-muted text-muted-foreground"}
                  to={d?.to}
                  isLoading={dashQ.isLoading}
                />
              );
            })}
          </div>
        )}

        {/* Attention Lists */}
        {listCfgs.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {listCfgs.map((cfg) => {
              if (cfg.type === "stale_conversations") return (
                <StaleConversationsWidget key={cfg.id} cfg={cfg} items={convQ.data?.items ?? []} isLoading={convQ.isLoading} />
              );
              if (cfg.type === "upcoming_appointments") return (
                <UpcomingAppointmentsWidget key={cfg.id} cfg={cfg} items={apptQ.data?.items ?? []} isLoading={apptQ.isLoading} />
              );
              if (cfg.type === "workflow_errors") return (
                <WorkflowErrorsWidget key={cfg.id} cfg={cfg} />
              );
              if (cfg.type === "high_score_leads") return (
                <HighScoreLeadsWidget key={cfg.id} cfg={cfg} items={leadsQ.data?.items ?? []} isLoading={leadsQ.isLoading} />
              );
              return null;
            })}
          </div>
        )}

        {/* Charts Row */}
        {chartCfgs.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {chartCfgs.map((cfg) => {
              if (cfg.type === "funnel") return (
                <FunnelWidget key={cfg.id} cfg={cfg} data={funnelQ.data} isLoading={funnelQ.isLoading} />
              );
              if (cfg.type === "activity_heatmap") return (
                <HeatmapWidget key={cfg.id} cfg={cfg} activityChart={activityChart} volumeBuckets={volumeBuckets} isLoading={dashQ.isLoading || volumeQ.isLoading} />
              );
              return null;
            })}
          </div>
        )}

        {/* Settings Dialog */}
        <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} configs={configs} wc={wc} />

        {/* Command Palette */}
        <CmdPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
      </div>
    </TooltipProvider>
  );
}

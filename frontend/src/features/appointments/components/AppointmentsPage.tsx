import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  CalendarDays,
  CalendarPlus,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Copy,
  Download,
  Filter,
  LayoutList,
  MapPin,
  MessageCircle,
  MoreVertical,
  PauseCircle,
  Phone,
  RefreshCw,
  Route,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
  UserRound,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { create } from "zustand";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  appointmentsApi,
  type AdvisorOption,
  type AppointmentItem,
  type AppointmentStatus,
  type AppointmentType,
  type FunnelStage,
  type NaturalParse,
  type PriorityItem,
  type SupervisorRecommendations,
  type VehicleOption,
} from "@/features/appointments/api";
import { customersApi, type CustomerListItem } from "@/features/customers/api";
import { DemoBadge } from "@/components/DemoBadge";
import { NYIButton } from "@/components/NYIButton";
import { cn } from "@/lib/utils";

type ViewMode = "operation" | "list" | "day" | "week" | "advisor";
type QuickFilter = "all" | "unconfirmed" | "high_risk" | "missing_advisor" | "missing_vehicle" | "incomplete_docs";

interface AppointmentUiState {
  selectedAppointmentId: string | null;
  activeView: ViewMode;
  quickFilter: QuickFilter;
  contextMenu: { x: number; y: number; appointmentId: string } | null;
  setSelectedAppointmentId: (id: string | null) => void;
  setActiveView: (view: ViewMode) => void;
  setQuickFilter: (filter: QuickFilter) => void;
  setContextMenu: (state: { x: number; y: number; appointmentId: string } | null) => void;
}

const useAppointmentUi = create<AppointmentUiState>((set) => ({
  selectedAppointmentId: null,
  activeView: "operation",
  quickFilter: "all",
  contextMenu: null,
  setSelectedAppointmentId: (id) => set({ selectedAppointmentId: id }),
  setActiveView: (view) => set({ activeView: view }),
  setQuickFilter: (filter) => set({ quickFilter: filter }),
  setContextMenu: (state) => set({ contextMenu: state }),
}));

const HOUR_START = 8;
const HOUR_END = 20;
const HOUR_HEIGHT = 58;
const DAY_MS = 86_400_000;

const viewLabels: Array<{ id: ViewMode; label: string; icon: ReactNode }> = [
  { id: "operation", label: "Operación", icon: <Zap className="h-3.5 w-3.5" /> },
  { id: "list", label: "Lista", icon: <LayoutList className="h-3.5 w-3.5" /> },
  { id: "day", label: "Día", icon: <Clock3 className="h-3.5 w-3.5" /> },
  { id: "week", label: "Semana", icon: <CalendarDays className="h-3.5 w-3.5" /> },
  { id: "advisor", label: "Asesor", icon: <Users className="h-3.5 w-3.5" /> },
];

const filterLabels: Array<{ id: QuickFilter; label: string }> = [
  { id: "all", label: "Todas" },
  { id: "unconfirmed", label: "Sin confirmar" },
  { id: "high_risk", label: "Alto riesgo" },
  { id: "missing_advisor", label: "Sin asesor" },
  { id: "missing_vehicle", label: "Sin unidad" },
  { id: "incomplete_docs", label: "Docs incompletos" },
];

const statusLabel: Record<AppointmentStatus, string> = {
  scheduled: "Programada",
  confirmed: "Confirmada",
  arrived: "Llegó",
  completed: "Completada",
  cancelled: "Cancelada",
  no_show: "No asistió",
  rescheduled: "Reprogramada",
};

const typeLabel: Record<AppointmentType, string> = {
  test_drive: "Prueba de manejo",
  quote: "Cotización",
  documents: "Documentos",
  delivery: "Entrega",
  follow_up: "Seguimiento",
  financing: "Financiamiento",
  call: "Llamada",
};

const typeTone: Record<AppointmentType, string> = {
  test_drive: "border-blue-400/60 bg-blue-500/12 text-blue-100",
  quote: "border-violet-400/60 bg-violet-500/12 text-violet-100",
  documents: "border-fuchsia-400/60 bg-fuchsia-500/12 text-fuchsia-100",
  delivery: "border-amber-400/60 bg-amber-500/12 text-amber-100",
  follow_up: "border-emerald-400/60 bg-emerald-500/12 text-emerald-100",
  financing: "border-sky-400/60 bg-sky-500/12 text-sky-100",
  call: "border-purple-400/60 bg-purple-500/12 text-purple-100",
};

function startOfWeek(date: Date): Date {
  const next = new Date(date);
  const day = next.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  next.setDate(next.getDate() + diff);
  next.setHours(0, 0, 0, 0);
  return next;
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function fmtTime(value: string | Date): string {
  return new Date(value).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function fmtDay(value: string | Date): string {
  return new Date(value).toLocaleDateString("es-MX", { weekday: "short", day: "numeric", month: "short" });
}

function currency(value: number): string {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 }).format(value);
}

function appointmentTop(item: AppointmentItem): number {
  const date = new Date(item.scheduled_at);
  const minutes = (date.getHours() - HOUR_START) * 60 + date.getMinutes();
  return Math.max(0, (minutes / 60) * HOUR_HEIGHT);
}

function appointmentHeight(item: AppointmentItem): number {
  const start = new Date(item.scheduled_at).getTime();
  const end = new Date(item.ends_at ?? start + 45 * 60_000).getTime();
  return Math.max(44, ((end - start) / 3_600_000) * HOUR_HEIGHT);
}

function riskClass(level: string): string {
  if (level === "critical") return "border-red-400/50 bg-red-500/15 text-red-100";
  if (level === "high") return "border-orange-400/50 bg-orange-500/15 text-orange-100";
  if (level === "medium") return "border-amber-400/50 bg-amber-500/15 text-amber-100";
  return "border-emerald-400/50 bg-emerald-500/15 text-emerald-100";
}

function statusClass(status: AppointmentStatus): string {
  if (status === "completed") return "bg-emerald-500/20 text-emerald-100";
  if (status === "confirmed" || status === "arrived") return "bg-blue-500/20 text-blue-100";
  if (status === "no_show" || status === "cancelled") return "bg-red-500/20 text-red-100";
  if (status === "rescheduled") return "bg-amber-500/20 text-amber-100";
  return "bg-slate-600/30 text-slate-200";
}

function matchesFilter(item: AppointmentItem, filter: QuickFilter): boolean {
  if (filter === "all") return true;
  if (filter === "unconfirmed") return item.status === "scheduled";
  if (filter === "high_risk") return item.risk_level === "high" || item.risk_level === "critical";
  if (filter === "missing_advisor") return !item.advisor_name;
  if (filter === "missing_vehicle") return item.appointment_type === "test_drive" && !item.vehicle_label;
  if (filter === "incomplete_docs") return !item.documents_complete;
  return true;
}

function Panel({ title, icon, action, children, className }: { title: string; icon?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-white/10 bg-slate-950/78 shadow-sm shadow-black/20", className)}>
      <div className="flex min-h-10 items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          {icon}
          {title}
        </div>
        {action}
      </div>
      <div className="p-3">{children}</div>
    </section>
  );
}

function KpiCard({ label, value, detail, tone = "slate" }: { label: string; value: string | number; detail?: string; tone?: "slate" | "green" | "amber" | "red" | "blue" | "violet" }) {
  const color = {
    slate: "text-slate-100",
    green: "text-emerald-300",
    amber: "text-amber-300",
    red: "text-red-300",
    blue: "text-sky-300",
    violet: "text-violet-300",
  }[tone];
  return (
    <button
      type="button"
      onClick={() => toast.info(`${label}: ${value}`)}
      className="min-w-[132px] rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-left transition hover:border-sky-300/40 hover:bg-sky-500/10"
    >
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold leading-none", color)}>{value}</div>
      {detail ? <div className="mt-1 truncate text-[10px] text-slate-500">{detail}</div> : null}
    </button>
  );
}

function AppointmentCard({ item, onSelect, onContext, onDragStart }: { item: AppointmentItem; onSelect: () => void; onContext: (event: React.MouseEvent) => void; onDragStart?: (event: React.DragEvent) => void }) {
  return (
    <button
      type="button"
      draggable
      onDragStart={onDragStart}
      onClick={onSelect}
      onContextMenu={onContext}
      className={cn("absolute left-1 right-1 overflow-hidden rounded-md border p-2 text-left text-[11px] shadow-lg transition hover:-translate-y-0.5", typeTone[item.appointment_type])}
      style={{ top: appointmentTop(item), height: appointmentHeight(item) }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold leading-tight">{fmtTime(item.scheduled_at)} - {fmtTime(item.ends_at ?? item.scheduled_at)}</div>
          <div className="mt-0.5 truncate text-slate-100">{typeLabel[item.appointment_type]}</div>
          <div className="truncate text-slate-300">{item.customer_name ?? item.customer_phone}</div>
          <div className="truncate text-slate-400">{item.vehicle_label ?? item.advisor_name ?? "Sin asignar"}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {item.conflict_count > 0 ? <AlertTriangle className="h-3.5 w-3.5 text-red-300" /> : null}
          <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", statusClass(item.status))}>{statusLabel[item.status]}</span>
        </div>
      </div>
    </button>
  );
}

function WeekCalendar({
  items,
  weekStart,
  onSelect,
  onContext,
  onDropAppointment,
}: {
  items: AppointmentItem[];
  weekStart: Date;
  onSelect: (item: AppointmentItem) => void;
  onContext: (event: React.MouseEvent, item: AppointmentItem) => void;
  onDropAppointment: (id: string, nextStart: Date) => void;
}) {
  const days = Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
  const now = new Date();
  const gridHeight = (HOUR_END - HOUR_START) * HOUR_HEIGHT;
  const nowTop = ((now.getHours() - HOUR_START) * 60 + now.getMinutes()) / 60 * HOUR_HEIGHT;
  return (
    <Panel title={`${fmtDay(weekStart)} - ${fmtDay(addDays(weekStart, 6))}`} icon={<CalendarDays className="h-4 w-4 text-sky-300" />} className="overflow-hidden">
      <div className="grid grid-cols-[52px_repeat(7,minmax(120px,1fr))] overflow-auto">
        <div />
        {days.map((day) => (
          <div key={day.toISOString()} className={cn("border-l border-white/10 px-2 pb-2 text-center text-xs text-slate-400", isSameDay(day, now) && "text-sky-200")}>
            <span>{day.toLocaleDateString("es-MX", { weekday: "short" })}</span>
            <span className={cn("ml-1 inline-grid h-6 w-6 place-items-center rounded-full", isSameDay(day, now) && "bg-blue-600 text-white")}>{day.getDate()}</span>
          </div>
        ))}
        <div className="relative border-r border-white/10" style={{ height: gridHeight }}>
          {Array.from({ length: HOUR_END - HOUR_START + 1 }, (_, index) => (
            <div key={index} className="absolute right-2 text-[10px] text-slate-500" style={{ top: index * HOUR_HEIGHT - 7 }}>
              {String(HOUR_START + index).padStart(2, "0")}:00
            </div>
          ))}
        </div>
        {days.map((day) => {
          const dayItems = items.filter((item) => isSameDay(new Date(item.scheduled_at), day));
          return (
            <div
              key={day.toISOString()}
              className={cn("relative border-l border-white/10", isSameDay(day, now) && "bg-sky-500/[0.03]")}
              style={{ height: gridHeight }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const id = event.dataTransfer.getData("appointment/id");
                if (!id) return;
                const rect = event.currentTarget.getBoundingClientRect();
                const y = Math.max(0, Math.min(gridHeight, event.clientY - rect.top));
                const minutes = Math.round((y / HOUR_HEIGHT) * 60 / 15) * 15;
                const next = new Date(day);
                next.setHours(HOUR_START, minutes, 0, 0);
                onDropAppointment(id, next);
              }}
            >
              {Array.from({ length: HOUR_END - HOUR_START + 1 }, (_, index) => (
                <div key={index} className="absolute left-0 right-0 border-t border-white/5" style={{ top: index * HOUR_HEIGHT }} />
              ))}
              {isSameDay(day, now) && now.getHours() >= HOUR_START && now.getHours() <= HOUR_END ? (
                <div className="absolute left-0 right-0 z-10 flex items-center" style={{ top: nowTop }}>
                  <span className="rounded-r bg-red-500 px-1 text-[10px] font-semibold text-white">{fmtTime(now)}</span>
                  <span className="flex-1 border-t border-red-500" />
                </div>
              ) : null}
              {dayItems.length === 0 ? (
                <div className="absolute inset-x-2 bottom-3 rounded-lg border border-dashed border-white/10 p-3 text-center text-xs text-slate-500">
                  Día sin citas
                </div>
              ) : null}
              {dayItems.map((item) => (
                <AppointmentCard
                  key={item.id}
                  item={item}
                  onSelect={() => onSelect(item)}
                  onContext={(event) => onContext(event, item)}
                  onDragStart={(event) => event.dataTransfer.setData("appointment/id", item.id)}
                />
              ))}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function ListView({ items, onSelect, onContext }: { items: AppointmentItem[]; onSelect: (item: AppointmentItem) => void; onContext: (event: React.MouseEvent, item: AppointmentItem) => void }) {
  const grouped = useMemo(() => {
    const map = new Map<string, AppointmentItem[]>();
    for (const item of items) {
      const key = new Date(item.scheduled_at).toDateString();
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return Array.from(map.entries()).map(([key, rows]) => ({ key, date: new Date(key), rows }));
  }, [items]);
  return (
    <Panel title="Vista: Lista" icon={<LayoutList className="h-4 w-4 text-sky-300" />}>
      <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
        {grouped.map((group) => (
          <div key={group.key}>
            <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
              <span>{fmtDay(group.date)}</span>
              <span>{group.rows.length} citas</span>
            </div>
            <div className="space-y-1.5">
              {group.rows.map((item) => (
                <button key={item.id} type="button" onClick={() => onSelect(item)} onContextMenu={(event) => onContext(event, item)} className="grid w-full grid-cols-[80px_1fr_120px_100px] items-center gap-3 rounded-md border border-white/10 bg-white/[0.035] px-3 py-2 text-left text-xs hover:border-sky-300/40">
                  <span className="font-mono text-slate-400">{fmtTime(item.scheduled_at)}</span>
                  <span className="min-w-0">
                    <span className="block truncate font-semibold text-slate-100">{item.customer_name ?? item.customer_phone}</span>
                    <span className="block truncate text-slate-500">{typeLabel[item.appointment_type]} · {item.vehicle_label ?? "Sin unidad"}</span>
                  </span>
                  <span className="truncate text-slate-300">{item.advisor_name ?? "Sin asesor"}</span>
                  <span className={cn("rounded px-2 py-1 text-center", statusClass(item.status))}>{statusLabel[item.status]}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function AdvisorView({ items, advisors, onSelect, onContext }: { items: AppointmentItem[]; advisors: AdvisorOption[]; onSelect: (item: AppointmentItem) => void; onContext: (event: React.MouseEvent, item: AppointmentItem) => void }) {
  return (
    <Panel title="Vista: Asesor" icon={<Users className="h-4 w-4 text-emerald-300" />} action={<DemoBadge className="ml-1.5 inline-block" />}>
      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {advisors.map((advisor) => {
          const rows = items.filter((item) => item.advisor_name === advisor.name);
          return (
            <div key={advisor.id} className="rounded-lg border border-white/10 bg-white/[0.035] p-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-100">{advisor.name}</div>
                  <div className="text-[11px] text-slate-500">{rows.length}/{advisor.max_per_day} citas · cierre {Math.round(advisor.close_rate * 100)}%</div>
                </div>
                <Badge variant="outline" className={rows.length > advisor.max_per_day ? "border-red-300/30 text-red-200" : "border-emerald-300/30 text-emerald-200"}>
                  {rows.length > advisor.max_per_day ? "Saturado" : "Disponible"}
                </Badge>
              </div>
              <div className="mt-3 space-y-1.5">
                {rows.slice(0, 5).map((item) => (
                  <button key={item.id} type="button" onClick={() => onSelect(item)} onContextMenu={(event) => onContext(event, item)} className="w-full rounded-md border border-white/10 bg-black/20 px-2 py-2 text-left text-xs hover:border-sky-300/40">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-slate-400">{fmtTime(item.scheduled_at)}</span>
                      <span className={cn("rounded px-1.5 py-0.5 text-[10px]", riskClass(item.risk_level))}>{item.risk_score}</span>
                    </div>
                    <div className="mt-1 truncate text-slate-100">{item.customer_name ?? item.customer_phone}</div>
                    <div className="truncate text-slate-500">{item.vehicle_label ?? typeLabel[item.appointment_type]}</div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function PriorityFeed({ items, onAction, onSelect }: { items: PriorityItem[]; onAction: (id: string, action: string) => void; onSelect: (id: string) => void }) {
  return (
    <Panel title="Qué requiere atención ahora" icon={<AlertTriangle className="h-4 w-4 text-amber-300" />}>
      <div className="max-h-[360px] space-y-2 overflow-auto pr-1">
        {items.map((item) => (
          <div key={item.id} className={cn("rounded-lg border p-3", riskClass(item.severity))}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-sm font-semibold">{item.reason}</div>
                <div className="mt-1 text-xs text-slate-300">{item.customer} · {fmtDay(item.time)} {fmtTime(item.time)}</div>
                <div className="text-xs text-slate-400">{item.vehicle ?? "Sin unidad"} · {item.recommended_action}</div>
              </div>
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onSelect(item.appointment_id)}>
                <MoreVertical className="h-4 w-4" />
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {item.actions.map((action) => (
                <Button key={action} size="sm" variant="outline" className="h-7 border-white/10 bg-black/20 text-[11px]" onClick={() => onAction(item.appointment_id, action)}>
                  {action === "send-reminder" ? "Enviar WhatsApp" : action === "reschedule" ? "Reprogramar" : action === "confirm" ? "Confirmar" : "Seguimiento"}
                </Button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function SmartAppointmentPanel({
  parsed,
  input,
  setInput,
  onParse,
  onCreate,
  parsing,
  creating,
}: {
  parsed: NaturalParse | null;
  input: string;
  setInput: (value: string) => void;
  onParse: () => void;
  onCreate: () => void;
  parsing: boolean;
  creating: boolean;
}) {
  return (
    <Panel title="Nueva cita inteligente" icon={<Sparkles className="h-4 w-4 text-emerald-300" />}>
      <Textarea value={input} onChange={(event) => setInput(event.target.value)} className="min-h-20 border-emerald-400/30 bg-emerald-500/5 text-sm text-slate-100" />
      <div className="mt-2 flex gap-2">
        <Button size="sm" className="h-8 bg-emerald-600 text-xs hover:bg-emerald-500" onClick={onParse} disabled={parsing || !input.trim()}>
          {parsing ? "Interpretando..." : "Interpretar"}
        </Button>
        <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs text-slate-200" onClick={() => setInput("Mañana 4pm prueba de manejo para Gabriel, trae 10 mil de enganche")}>
          Ejemplo
        </Button>
      </div>
      {parsed ? (
        <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.035] p-3 text-xs">
          <div className="mb-2 flex items-center gap-2 text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Entendido · confianza {Math.round(parsed.confidence * 100)}%
          </div>
          {[
            ["Fecha", parsed.date ?? "-"],
            ["Hora", parsed.time ?? "-"],
            ["Tipo", typeLabel[parsed.appointment_type]],
            ["Cliente", parsed.customer_name ?? "No especificado"],
            ["Unidad", parsed.vehicle_label ?? "Pendiente"],
            ["Enganche", parsed.down_payment_amount ? currency(parsed.down_payment_amount) : "No detectado"],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3 border-b border-white/5 py-1.5 last:border-b-0">
              <span className="text-slate-500">{label}</span>
              <span className="text-right text-slate-200">{value}</span>
            </div>
          ))}
          {parsed.missing_fields.length > 0 ? <div className="mt-2 text-amber-300">Falta: {parsed.missing_fields.join(", ")}</div> : null}
        </div>
      ) : null}
      <Button className="mt-3 w-full bg-emerald-600 hover:bg-emerald-500" onClick={onCreate} disabled={!parsed || creating}>
        <CalendarPlus className="mr-2 h-4 w-4" />
        {creating ? "Creando..." : "Crear cita"}
      </Button>
    </Panel>
  );
}

function DetailPanel({ item, advisors, vehicles, onAction, onPatch }: { item: AppointmentItem; advisors: AdvisorOption[]; vehicles: VehicleOption[]; onAction: (id: string, action: string) => void; onPatch: (id: string, body: Partial<AppointmentItem>) => void }) {
  return (
    <Panel title="Detalle de cita" icon={<CalendarDays className="h-4 w-4 text-sky-300" />} action={<DemoBadge className="ml-1.5 inline-block" />}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-base font-semibold text-slate-100">{typeLabel[item.appointment_type]}</div>
          <div className="text-xs text-slate-400">{fmtDay(item.scheduled_at)} · {fmtTime(item.scheduled_at)} · {Math.round((new Date(item.ends_at ?? item.scheduled_at).getTime() - new Date(item.scheduled_at).getTime()) / 60_000)} min</div>
        </div>
        <Badge className={statusClass(item.status)}>{statusLabel[item.status]}</Badge>
      </div>
      <div className="mt-3 grid gap-2 text-xs">
        {[
          ["Cliente", item.customer_name ?? item.customer_phone],
          ["WhatsApp", item.customer_phone],
          ["Asesor", item.advisor_name ?? "Sin asesor"],
          ["Unidad", item.vehicle_label ?? "Sin unidad"],
          ["Plan", item.credit_plan ?? "Sin plan"],
          ["Enganche", item.down_payment_amount ? `${currency(item.down_payment_amount)} · ${item.down_payment_confirmed ? "confirmado" : "pendiente"}` : "No aplica"],
          ["Documentos", item.documents_complete ? "Completos" : "Pendientes"],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 rounded-md border border-white/10 bg-white/[0.035] px-3 py-2">
            <span className="text-slate-500">{label}</span>
            <span className="text-right text-slate-200">{value}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.035] p-3 text-xs">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-slate-400">Risk score</span>
          <Badge variant="outline" className={riskClass(item.risk_level)}>{item.risk_score}/100</Badge>
        </div>
        <div className="space-y-1">
          {(item.risk_reasons.length ? item.risk_reasons : [{ code: "ok", message: "Sin riesgos críticos" }]).slice(0, 4).map((reason) => (
            <div key={reason.code} className="text-slate-300">• {reason.message}</div>
          ))}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button size="sm" className="h-8 bg-blue-600 text-xs hover:bg-blue-500" onClick={() => onAction(item.id, "send-reminder")}><MessageCircle className="mr-1.5 h-3.5 w-3.5" /> WhatsApp</Button>
        <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs" onClick={() => onAction(item.id, "send-location")}><MapPin className="mr-1.5 h-3.5 w-3.5" /> Ubicación</Button>
        <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs" onClick={() => onAction(item.id, "request-documents")}>Docs</Button>
        <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs" onClick={() => onAction(item.id, "create-follow-up")}>Seguimiento</Button>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <select className="h-8 rounded-md border border-white/10 bg-slate-950 px-2" value={item.advisor_name ?? ""} onChange={(event) => {
          const advisor = advisors.find((entry) => entry.name === event.target.value);
          if (advisor) onPatch(item.id, { advisor_id: advisor.id, advisor_name: advisor.name } as Partial<AppointmentItem>);
        }}>
          <option value="">Cambiar asesor</option>
          {advisors.map((advisor) => <option key={advisor.id} value={advisor.name}>{advisor.name}</option>)}
        </select>
        <select className="h-8 rounded-md border border-white/10 bg-slate-950 px-2" value={item.vehicle_label ?? ""} onChange={(event) => {
          const vehicle = vehicles.find((entry) => entry.label === event.target.value);
          if (vehicle) onPatch(item.id, { vehicle_id: vehicle.id, vehicle_label: vehicle.label } as Partial<AppointmentItem>);
        }}>
          <option value="">Cambiar unidad</option>
          {vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.label}>{vehicle.label}</option>)}
        </select>
      </div>
      <div className="mt-3 max-h-32 space-y-1 overflow-auto text-[11px] text-slate-400">
        {item.action_log.slice(0, 5).map((log, index) => (
          <div key={String(log.id ?? index)} className="rounded border border-white/10 bg-black/20 px-2 py-1">
            {String(log.action ?? "acción")} · {String(log.actor ?? "Sistema")}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function SupervisorPanel({ data, onRun }: { data: SupervisorRecommendations | undefined; onRun: () => void }) {
  return (
    <Panel title="AI Agenda Supervisor" icon={<Bot className="h-4 w-4 text-violet-300" />} action={<Button size="sm" variant="outline" className="h-7 border-white/10 bg-white/[0.035] text-xs" onClick={onRun}>Ejecutar</Button>}>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="text-slate-400">Salud</span>
        <span className="font-semibold text-emerald-300">{data?.health ?? "Sin datos"}</span>
      </div>
      <div className="space-y-2">
        {(data?.recommendations ?? []).map((item) => (
          <div key={item.id} className="rounded-lg border border-white/10 bg-white/[0.035] p-2 text-xs">
            <div className="font-semibold text-slate-100">{item.title}</div>
            <div className="mt-1 text-slate-400">{item.detail}</div>
            <div className="mt-2">
              <NYIButton label={item.action} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {(data?.open_slots ?? []).map((slot) => (
          <Badge key={`${slot.advisor}-${slot.time}`} variant="outline" className="border-emerald-300/30 text-emerald-200">{slot.advisor} {slot.time}</Badge>
        ))}
      </div>
    </Panel>
  );
}

function FunnelPanel({ stages }: { stages: FunnelStage[] | undefined }) {
  const max = Math.max(...(stages ?? []).map((stage) => stage.count), 1);
  return (
    <div className="border-t border-white/10 bg-slate-950 px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-100">
        <Route className="h-4 w-4 text-emerald-300" />
        Embudo de citas a venta
      </div>
      <div className="grid gap-2 md:grid-cols-7">
        {(stages ?? []).map((stage) => (
          <button key={stage.stage} type="button" onClick={() => toast.info(`${stage.stage}: ${stage.conversion}%`)} className="rounded-lg border border-white/10 bg-white/[0.035] p-2 text-left text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">{stage.stage}</span>
              <span className={stage.trend >= 0 ? "text-emerald-300" : "text-red-300"}>{stage.trend >= 0 ? "+" : ""}{stage.trend}%</span>
            </div>
            <div className="mt-2 text-xl font-semibold text-slate-100">{stage.count}</div>
            <div className="mt-2 h-1.5 rounded bg-white/10">
              <div className="h-full rounded bg-emerald-400" style={{ width: `${Math.max(8, (stage.count / max) * 100)}%` }} />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function ContextMenu({ appointment, x, y, onClose, onAction }: { appointment: AppointmentItem; x: number; y: number; onClose: () => void; onAction: (id: string, action: string) => void }) {
  const actions = [
    ["open-chat", "Abrir conversación WhatsApp", MessageCircle],
    ["confirm", "Confirmar cita", CheckCircle2],
    ["send-location", "Enviar ubicación", MapPin],
    ["send-reminder", "Enviar recordatorio", Send],
    ["request-documents", "Solicitar documentos", Upload],
    ["mark-arrived", "Marcar como llegó", UserRound],
    ["mark-completed", "Marcar completada", ShieldCheck],
    ["mark-no-show", "Marcar no asistió", AlertTriangle],
    ["reschedule", "Reprogramar", RefreshCw],
    ["cancel", "Cancelar cita", PauseCircle],
  ] as const;
  return (
    <div className="fixed inset-0 z-50" onClick={onClose}>
      <div className="absolute w-56 rounded-lg border border-white/10 bg-slate-950 p-1 text-xs text-slate-200 shadow-2xl" style={{ left: x, top: y }}>
        <div className="border-b border-white/10 px-2 py-2 text-[11px] text-slate-500">{appointment.customer_name ?? appointment.customer_phone}</div>
        {actions.map(([id, label, Icon]) => (
          <button key={id} type="button" onClick={(event) => { event.stopPropagation(); onAction(appointment.id, id); onClose(); }} className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-white/10">
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function AppointmentsPage() {
  const queryClient = useQueryClient();
  const { selectedAppointmentId, activeView, quickFilter, contextMenu, setSelectedAppointmentId, setActiveView, setQuickFilter, setContextMenu } = useAppointmentUi();
  const [anchorDate, setAnchorDate] = useState(new Date());
  const [query, setQuery] = useState("");
  const [smartInput, setSmartInput] = useState("Mañana 4pm prueba de manejo para Gabriel, trae 10 mil de enganche");
  const [parsed, setParsed] = useState<NaturalParse | null>(null);

  const weekStart = useMemo(() => startOfWeek(anchorDate), [anchorDate]);
  const dateFrom = useMemo(() => {
    const date = activeView === "day" ? new Date(anchorDate) : weekStart;
    date.setHours(0, 0, 0, 0);
    return date.toISOString();
  }, [activeView, anchorDate, weekStart]);
  const dateTo = useMemo(() => {
    const date = activeView === "day" ? addDays(anchorDate, 1) : addDays(weekStart, 7);
    date.setHours(0, 0, 0, 0);
    return date.toISOString();
  }, [activeView, anchorDate, weekStart]);

  const appointmentsQuery = useQuery({
    queryKey: ["appointments", "command-center", dateFrom, dateTo],
    queryFn: () => appointmentsApi.list({ date_from: dateFrom, date_to: dateTo, limit: 300 }),
  });
  const kpisQuery = useQuery({ queryKey: ["appointments", "kpis"], queryFn: appointmentsApi.kpis });
  const priorityQuery = useQuery({ queryKey: ["appointments", "priority"], queryFn: appointmentsApi.priorityFeed });
  const funnelQuery = useQuery({ queryKey: ["appointments", "funnel"], queryFn: appointmentsApi.funnel });
  const supervisorQuery = useQuery({ queryKey: ["appointments", "supervisor"], queryFn: appointmentsApi.supervisor });
  const advisorsQuery = useQuery({ queryKey: ["appointments", "advisors"], queryFn: appointmentsApi.advisors });
  const vehiclesQuery = useQuery({ queryKey: ["appointments", "vehicles"], queryFn: appointmentsApi.vehicles });
  const customersQuery = useQuery({ queryKey: ["customers", "appointments"], queryFn: () => customersApi.list({ limit: 200 }) });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["appointments"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const items = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (appointmentsQuery.data?.items ?? [])
      .filter((item) => matchesFilter(item, quickFilter))
      .filter((item) => !needle || `${item.customer_name ?? ""} ${item.customer_phone} ${item.service} ${item.vehicle_label ?? ""} ${item.advisor_name ?? ""}`.toLowerCase().includes(needle));
  }, [appointmentsQuery.data?.items, quickFilter, query]);
  const selected = (appointmentsQuery.data?.items ?? []).find((item) => item.id === selectedAppointmentId) ?? items[0] ?? null;
  const menuAppointment = contextMenu ? (appointmentsQuery.data?.items ?? []).find((item) => item.id === contextMenu.appointmentId) : null;

  const actionMutation = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: string }) => {
      if (action === "confirm") return appointmentsApi.confirm(id);
      if (action === "send-reminder") return appointmentsApi.sendReminder(id);
      if (action === "send-location") return appointmentsApi.sendLocation(id);
      if (action === "request-documents") return appointmentsApi.requestDocuments(id);
      if (action === "mark-arrived") return appointmentsApi.markArrived(id);
      if (action === "mark-completed") return appointmentsApi.markCompleted(id);
      if (action === "mark-no-show") return appointmentsApi.markNoShow(id);
      if (action === "create-follow-up") return appointmentsApi.createFollowUp(id);
      if (action === "cancel") return appointmentsApi.patch(id, { status: "cancelled" });
      if (action === "open-chat") return Promise.resolve(selected);
      if (action === "reschedule") {
        const base = new Date();
        base.setHours(base.getHours() + 2, 0, 0, 0);
        return appointmentsApi.reschedule(id, base.toISOString());
      }
      return Promise.resolve(selected);
    },
    onSuccess: (_, variables) => {
      if (variables.action === "open-chat") toast.info("Conversación de WhatsApp preparada");
      else toast.success("Acción ejecutada");
      invalidate();
    },
    onError: (error: Error) => toast.error("No se pudo ejecutar", { description: error.message }),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<AppointmentItem> }) => appointmentsApi.patch(id, body),
    onSuccess: () => {
      toast.success("Cita actualizada");
      invalidate();
    },
    onError: (error: Error) => toast.error("No se pudo actualizar", { description: error.message }),
  });

  const parseMutation = useMutation({
    mutationFn: () => appointmentsApi.parseNatural(smartInput),
    onSuccess: (result) => {
      setParsed(result);
      toast.success("Entrada interpretada");
    },
    onError: (error: Error) => toast.error("No se pudo interpretar", { description: error.message }),
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!parsed?.scheduled_at) throw new Error("Primero interpreta la cita");
      const customers = customersQuery.data?.items ?? [];
      const customer = findCustomerForParsed(parsed, customers);
      if (!customer) throw new Error("No hay cliente disponible para asociar la cita");
      const vehicle = vehiclesQuery.data?.find((entry) => entry.label === parsed.vehicle_label);
      const advisor = advisorsQuery.data?.find((entry) => entry.name === parsed.advisor_name);
      return appointmentsApi.create({
        customer_id: customer.id,
        scheduled_at: parsed.scheduled_at,
        ends_at: parsed.ends_at,
        appointment_type: parsed.appointment_type,
        service: parsed.service,
        source: "ai_parser",
        ai_confidence: parsed.confidence,
        vehicle_id: vehicle?.id ?? null,
        vehicle_label: parsed.vehicle_label,
        advisor_id: advisor?.id ?? null,
        advisor_name: parsed.advisor_name,
        down_payment_amount: parsed.down_payment_amount,
        documents_complete: false,
        notes: smartInput,
      });
    },
    onSuccess: (result) => {
      setSelectedAppointmentId(result.appointment.id);
      toast.success("Cita creada");
      invalidate();
    },
    onError: (error: Error) => toast.error("No se pudo crear", { description: error.message }),
  });

  const rescheduleMutation = useMutation({
    mutationFn: ({ id, date }: { id: string; date: Date }) => appointmentsApi.reschedule(id, date.toISOString()),
    onSuccess: () => {
      toast.success("Cita reprogramada");
      invalidate();
    },
    onError: (error: Error) => toast.error("No se pudo reprogramar", { description: error.message }),
  });

  function handleAction(id: string, action: string) {
    actionMutation.mutate({ id, action });
  }

  const kpis = kpisQuery.data;

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-950 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex min-w-52 items-center gap-2">
            <CalendarDays className="h-5 w-5 text-sky-300" />
            <div>
              <div className="text-xl font-semibold">Citas</div>
              <div className="text-[11px] text-slate-500">Appointment Command Center</div>
            </div>
          </div>
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} className="h-9 border-white/10 bg-black/20 pl-9 text-sm text-slate-100" placeholder="Buscar cita, cliente, asesor, unidad..." />
          </div>
          <Badge variant="outline" className="h-8 border-emerald-400/30 bg-emerald-500/10 text-emerald-200">En vivo</Badge>
          <Badge variant="outline" className="h-8 border-sky-400/30 bg-sky-500/10 text-sky-200">IA · {supervisorQuery.data?.health ?? "Sincronizada"}</Badge>
          <NYIButton label="Importar CSV" icon={Download} />
          <Button size="sm" className="h-9 bg-blue-600 text-xs hover:bg-blue-500" onClick={() => parseMutation.mutate()}>
            <CalendarPlus className="mr-1.5 h-3.5 w-3.5" />
            Nueva cita
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-white/10 bg-black/20 p-1">
            {viewLabels.map((view) => (
              <button key={view.id} type="button" onClick={() => setActiveView(view.id)} className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition", activeView === view.id ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-white/10 hover:text-slate-100")}>
                {view.icon}
                {view.label}
              </button>
            ))}
          </div>
          <Button size="sm" variant="outline" className="h-8 border-white/10 bg-white/[0.035] text-xs" onClick={() => setAnchorDate(new Date())}>Hoy</Button>
          <Button size="icon" variant="outline" className="h-8 w-8 border-white/10 bg-white/[0.035]" onClick={() => setAnchorDate(addDays(anchorDate, activeView === "day" ? -1 : -7))}><ChevronLeft className="h-4 w-4" /></Button>
          <Button size="icon" variant="outline" className="h-8 w-8 border-white/10 bg-white/[0.035]" onClick={() => setAnchorDate(addDays(anchorDate, activeView === "day" ? 1 : 7))}><ChevronRight className="h-4 w-4" /></Button>
          <div className="ml-auto flex flex-wrap gap-1.5">
            {filterLabels.map((filter) => (
              <button key={filter.id} type="button" onClick={() => setQuickFilter(filter.id)} className={cn("rounded-md border px-2.5 py-1.5 text-xs transition", quickFilter === filter.id ? "border-sky-300/60 bg-sky-500/15 text-sky-100" : "border-white/10 bg-white/[0.035] text-slate-400 hover:text-slate-100")}>
                {filter.label}
              </button>
            ))}
            <NYIButton label="Filtros avanzados" icon={Filter} />
          </div>
        </div>
        <div className="mt-3 flex gap-2 overflow-x-auto">
          {kpisQuery.isLoading ? Array.from({ length: 7 }, (_, index) => <Skeleton key={index} className="h-16 min-w-[132px] bg-white/10" />) : (
            <>
              <KpiCard label="Citas hoy" value={kpis?.today ?? 0} tone="blue" />
              <KpiCard label="Confirmadas" value={kpis?.confirmed ?? 0} tone="green" />
              <KpiCard label="Alto riesgo" value={kpis?.high_risk ?? 0} tone="red" />
              <KpiCard label="No-show probable" value={kpis?.probable_no_show ?? 0} tone="amber" />
              <KpiCard label="Sin asesor" value={kpis?.missing_advisor ?? 0} tone="violet" />
              <KpiCard label="Docs incompletos" value={kpis?.incomplete_docs ?? 0} tone="amber" />
              <KpiCard label="Oportunidad MXN" value={currency(kpis?.estimated_opportunity_mxn ?? 0)} detail="Pipeline estimado" tone="green" />
            </>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className={cn("grid gap-3", activeView === "operation" ? "xl:grid-cols-[330px_minmax(0,1fr)_340px]" : "xl:grid-cols-[minmax(0,1fr)_340px]")}>
          {activeView === "operation" ? (
            <PriorityFeed
              items={priorityQuery.data ?? []}
              onAction={handleAction}
              onSelect={setSelectedAppointmentId}
            />
          ) : null}

          <div className="min-w-0 space-y-3">
            {appointmentsQuery.isLoading ? (
              <Skeleton className="h-[620px] rounded-lg bg-white/10" />
            ) : activeView === "list" ? (
              <ListView items={items} onSelect={(item) => setSelectedAppointmentId(item.id)} onContext={(event, item) => { event.preventDefault(); setContextMenu({ x: event.clientX, y: event.clientY, appointmentId: item.id }); }} />
            ) : activeView === "advisor" ? (
              <AdvisorView items={items} advisors={advisorsQuery.data ?? []} onSelect={(item) => setSelectedAppointmentId(item.id)} onContext={(event, item) => { event.preventDefault(); setContextMenu({ x: event.clientX, y: event.clientY, appointmentId: item.id }); }} />
            ) : (
              <WeekCalendar
                items={activeView === "day" ? items.filter((item) => isSameDay(new Date(item.scheduled_at), anchorDate)) : items}
                weekStart={activeView === "day" ? anchorDate : weekStart}
                onSelect={(item) => setSelectedAppointmentId(item.id)}
                onContext={(event, item) => { event.preventDefault(); setContextMenu({ x: event.clientX, y: event.clientY, appointmentId: item.id }); }}
                onDropAppointment={(id, nextStart) => rescheduleMutation.mutate({ id, date: nextStart })}
              />
            )}
            {activeView !== "operation" ? (
              <PriorityFeed items={priorityQuery.data ?? []} onAction={handleAction} onSelect={setSelectedAppointmentId} />
            ) : null}
          </div>

          <aside className="space-y-3">
            <SmartAppointmentPanel
              parsed={parsed}
              input={smartInput}
              setInput={setSmartInput}
              onParse={() => parseMutation.mutate()}
              onCreate={() => createMutation.mutate()}
              parsing={parseMutation.isPending}
              creating={createMutation.isPending}
            />
            {selected ? (
              <DetailPanel
                item={selected}
                advisors={advisorsQuery.data ?? []}
                vehicles={vehiclesQuery.data ?? []}
                onAction={handleAction}
                onPatch={(id, body) => patchMutation.mutate({ id, body })}
              />
            ) : null}
            <SupervisorPanel data={supervisorQuery.data} onRun={() => toast.success("Sugerencias ejecutadas en modo seguro")} />
          </aside>
        </div>
      </div>

      <FunnelPanel stages={funnelQuery.data} />

      {contextMenu && menuAppointment ? (
        <ContextMenu
          appointment={menuAppointment}
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onAction={handleAction}
        />
      ) : null}
    </div>
  );
}

function findCustomerForParsed(parsed: NaturalParse, customers: CustomerListItem[]): CustomerListItem | null {
  if (parsed.customer_name) {
    const needle = parsed.customer_name.toLowerCase();
    const exact = customers.find((customer) => (customer.name ?? "").toLowerCase().includes(needle) || needle.includes((customer.name ?? "").toLowerCase()));
    if (exact) return exact;
  }
  return customers[0] ?? null;
}

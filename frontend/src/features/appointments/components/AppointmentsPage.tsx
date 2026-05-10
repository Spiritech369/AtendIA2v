import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  CalendarCheck,
  CalendarDays,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Clock,
  ExternalLink,
  LayoutList,
  Pencil,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  type AppointmentConflict,
  type AppointmentItem,
  appointmentsApi,
} from "@/features/appointments/api";
import { customersApi } from "@/features/customers/api";
import { AppointmentsFeatureSettings } from "./AppointmentsFeatureSettings";

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUSES = ["scheduled", "completed", "cancelled", "no_show"] as const;
type AppointmentStatus = (typeof STATUSES)[number];

const STATUS_LABEL: Record<string, string> = {
  scheduled: "Programada",
  completed: "Completada",
  cancelled: "Cancelada",
  no_show: "No asistió",
};

const STATUS_COLOR: Record<string, string> = {
  scheduled: "#3b82f6",
  completed: "#10b981",
  cancelled: "#6b7280",
  no_show: "#f59e0b",
};

const STATUS_BG: Record<string, string> = {
  scheduled: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  completed: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  cancelled: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
  no_show: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
};

const HOUR_START = 8;
const HOUR_END = 20;
const TOTAL_HOURS = HOUR_END - HOUR_START;
const HOUR_PX = 56;
const GRID_HEIGHT = TOTAL_HOURS * HOUR_PX;

const DAY_NAMES_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const DAY_NAMES_FULL = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];

const BUCKET_ORDER = ["Pasadas", "Hoy", "Mañana", "Esta semana", "Este mes", "Más adelante"];

// ─── Date utilities ────────────────────────────────────────────────────────────

function getMondayOf(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date: Date, n: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function fmtShort(date: Date): string {
  return date.toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
}

function fmtTime(date: Date): string {
  return date.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function toLocalInputValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function bucketLabel(scheduled: Date, now: Date): string {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const day = new Date(scheduled);
  day.setHours(0, 0, 0, 0);
  const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (diff < 0) return "Pasadas";
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Mañana";
  if (diff < 7) return "Esta semana";
  if (diff < 30) return "Este mes";
  return "Más adelante";
}

// ─── Smart input parser ────────────────────────────────────────────────────────

interface ParsedApt {
  date: Date;
  service: string;
}

function parseSmartInput(text: string): ParsedApt | null {
  if (!text.trim()) return null;
  const now = new Date();
  const date = new Date(now);
  date.setHours(9, 0, 0, 0);

  const lower = text.toLowerCase();

  if (lower.includes("mañana")) {
    date.setDate(date.getDate() + 1);
  } else if (!lower.includes("hoy")) {
    for (let i = 0; i < DAY_NAMES_FULL.length; i++) {
      if (lower.includes(DAY_NAMES_FULL[i]!)) {
        const targetJs = (i + 1) % 7; // Mon=1..Sun=0
        const todayJs = now.getDay();
        let diff = targetJs - todayJs;
        if (diff <= 0) diff += 7;
        date.setDate(date.getDate() + diff);
        break;
      }
    }
  }

  const timeRe = /(\d{1,2})(?::(\d{2}))?\s*(am|pm|hrs?)?/i;
  const tm = timeRe.exec(text);
  if (tm) {
    let h = parseInt(tm[1]!, 10);
    const m = tm[2] ? parseInt(tm[2], 10) : 0;
    const mer = tm[3]?.toLowerCase() ?? "";
    if (mer === "pm" && h < 12) h += 12;
    else if (mer === "am" && h === 12) h = 0;
    else if (!mer && h >= 1 && h <= 7) h += 12; // 1-7 no meridiem → PM
    date.setHours(h, m, 0, 0);
  }

  const service = text
    .replace(/\b(hoy|mañana|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b/gi, "")
    .replace(/\d{1,2}(?::\d{2})?\s*(?:am|pm|hrs?)?/gi, "")
    .trim()
    .replace(/\s{2,}/g, " ");

  if (!service) return null;
  return { date, service };
}

// ─── Conflict detection ────────────────────────────────────────────────────────

function detectConflicts(items: AppointmentItem[]): Set<string> {
  const ids = new Set<string>();
  const scheduled = items.filter((a) => a.status === "scheduled");
  for (let i = 0; i < scheduled.length; i++) {
    for (let j = i + 1; j < scheduled.length; j++) {
      const a = scheduled[i]!;
      const b = scheduled[j]!;
      if (a.customer_id !== b.customer_id) continue;
      const diff = Math.abs(
        new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
      );
      if (diff < 2 * 60 * 60 * 1000) {
        ids.add(a.id);
        ids.add(b.id);
      }
    }
  }
  return ids;
}

// ─── KPI Tile ─────────────────────────────────────────────────────────────────

function KPITile({
  label,
  value,
  icon: Icon,
  colorClass,
}: {
  label: string;
  value: number;
  icon: typeof CalendarDays;
  colorClass: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3 shrink-0">
      <div className={`grid h-9 w-9 place-items-center rounded-lg ${colorClass}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <div className="text-xl font-bold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

// ─── Appointment block (week/day views) ───────────────────────────────────────

function aptTop(iso: string): number {
  const d = new Date(iso);
  const mins = (d.getHours() - HOUR_START) * 60 + d.getMinutes();
  return Math.max(0, (mins / (TOTAL_HOURS * 60)) * GRID_HEIGHT);
}

function AppointmentBlock({
  item,
  hasConflict,
  onClick,
}: {
  item: AppointmentItem;
  hasConflict: boolean;
  onClick: () => void;
}) {
  const color = STATUS_COLOR[item.status] ?? "#6366f1";
  const top = aptTop(item.scheduled_at);

  return (
    <button
      type="button"
      onClick={onClick}
      style={{ top, height: 48, borderLeftColor: color }}
      className="absolute left-0.5 right-0.5 cursor-pointer overflow-hidden rounded-md border-l-4 bg-background p-1 text-left text-xs shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-1">
        <div className="min-w-0">
          <div className="truncate font-medium leading-tight">
            {item.customer_name ?? item.customer_phone}
          </div>
          <div className="truncate text-muted-foreground">{item.service}</div>
        </div>
        {hasConflict && <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />}
      </div>
    </button>
  );
}

// ─── Week View ─────────────────────────────────────────────────────────────────

function WeekView({
  weekStart,
  items,
  conflicts,
  onSelect,
}: {
  weekStart: Date;
  items: AppointmentItem[];
  conflicts: Set<string>;
  onSelect: (item: AppointmentItem) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const now = new Date();
  const nowMins = (now.getHours() - HOUR_START) * 60 + now.getMinutes();
  const nowTop = (nowMins / (TOTAL_HOURS * 60)) * GRID_HEIGHT;
  const showNowLine = now.getHours() >= HOUR_START && now.getHours() < HOUR_END;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = Math.max(0, nowTop - 100);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));

  const byDay = useMemo(() => {
    const map = new Map<string, AppointmentItem[]>();
    for (const item of items) {
      const d = new Date(item.scheduled_at);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      const arr = map.get(key) ?? [];
      arr.push(item);
      map.set(key, arr);
    }
    return map;
  }, [items]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 border-b">
        <div className="w-14 shrink-0 border-r" />
        {days.map((day, i) => {
          const isToday = isSameDay(day, now);
          return (
            <div
              key={i}
              className={`flex-1 border-r px-2 py-2 text-center text-xs last:border-r-0 ${isToday ? "bg-primary/5" : ""}`}
            >
              <div
                className={`font-medium ${isToday ? "text-primary" : "text-muted-foreground"}`}
              >
                {DAY_NAMES_SHORT[i]}
              </div>
              <div className={`text-sm ${isToday ? "font-bold text-primary" : ""}`}>
                {day.getDate()}
              </div>
            </div>
          );
        })}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="flex" style={{ height: GRID_HEIGHT }}>
          <div className="relative w-14 shrink-0 border-r">
            {Array.from({ length: TOTAL_HOURS }, (_, h) => (
              <div
                key={h}
                style={{ top: h * HOUR_PX - 7 }}
                className="absolute right-2 text-[10px] text-muted-foreground tabular-nums"
              >
                {String(HOUR_START + h).padStart(2, "0")}:00
              </div>
            ))}
          </div>

          {days.map((day, i) => {
            const key = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`;
            const dayItems = byDay.get(key) ?? [];
            const isToday = isSameDay(day, now);
            return (
              <div
                key={i}
                className={`relative flex-1 border-r last:border-r-0 ${isToday ? "bg-primary/[0.02]" : ""}`}
              >
                {Array.from({ length: TOTAL_HOURS }, (_, h) => (
                  <div
                    key={h}
                    style={{ top: h * HOUR_PX }}
                    className="absolute left-0 right-0 border-t border-border/40"
                  />
                ))}
                {Array.from({ length: TOTAL_HOURS }, (_, h) => (
                  <div
                    key={`hh${h}`}
                    style={{ top: h * HOUR_PX + HOUR_PX / 2 }}
                    className="absolute left-0 right-0 border-t border-border/20 border-dashed"
                  />
                ))}
                {showNowLine && isToday && (
                  <div
                    style={{ top: nowTop }}
                    className="absolute left-0 right-0 z-10 flex items-center"
                  >
                    <div className="-ml-1 h-2 w-2 rounded-full bg-red-500" />
                    <div className="flex-1 border-t-2 border-red-500" />
                  </div>
                )}
                {dayItems.map((item) => (
                  <AppointmentBlock
                    key={item.id}
                    item={item}
                    hasConflict={conflicts.has(item.id)}
                    onClick={() => onSelect(item)}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Day View ──────────────────────────────────────────────────────────────────

function DayView({
  date,
  items,
  conflicts,
  onSelect,
}: {
  date: Date;
  items: AppointmentItem[];
  conflicts: Set<string>;
  onSelect: (item: AppointmentItem) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const now = new Date();
  const nowMins = (now.getHours() - HOUR_START) * 60 + now.getMinutes();
  const nowTop = (nowMins / (TOTAL_HOURS * 60)) * GRID_HEIGHT;
  const showNowLine =
    isSameDay(date, now) && now.getHours() >= HOUR_START && now.getHours() < HOUR_END;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = Math.max(0, nowTop - 100);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dayItems = useMemo(
    () => items.filter((a) => isSameDay(new Date(a.scheduled_at), date)),
    [items, date],
  );

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b px-4 py-2">
        <div className="text-sm font-medium capitalize">
          {date.toLocaleDateString("es-MX", {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </div>
        <div className="text-xs text-muted-foreground">{dayItems.length} cita(s)</div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="flex" style={{ height: GRID_HEIGHT }}>
          <div className="relative w-14 shrink-0 border-r">
            {Array.from({ length: TOTAL_HOURS }, (_, h) => (
              <div
                key={h}
                style={{ top: h * HOUR_PX - 7 }}
                className="absolute right-2 text-[10px] text-muted-foreground tabular-nums"
              >
                {String(HOUR_START + h).padStart(2, "0")}:00
              </div>
            ))}
          </div>
          <div className="relative flex-1">
            {Array.from({ length: TOTAL_HOURS }, (_, h) => (
              <div
                key={h}
                style={{ top: h * HOUR_PX }}
                className="absolute left-0 right-0 border-t border-border/40"
              />
            ))}
            {Array.from({ length: TOTAL_HOURS }, (_, h) => (
              <div
                key={`hh${h}`}
                style={{ top: h * HOUR_PX + HOUR_PX / 2 }}
                className="absolute left-0 right-0 border-t border-border/20 border-dashed"
              />
            ))}
            {showNowLine && (
              <div
                style={{ top: nowTop }}
                className="absolute left-0 right-0 z-10 flex items-center"
              >
                <div className="-ml-1 h-2 w-2 rounded-full bg-red-500" />
                <div className="flex-1 border-t-2 border-red-500" />
              </div>
            )}
            {dayItems.map((item) => (
              <AppointmentBlock
                key={item.id}
                item={item}
                hasConflict={conflicts.has(item.id)}
                onClick={() => onSelect(item)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── List View ─────────────────────────────────────────────────────────────────

function ListView({
  items,
  conflicts,
  onSelect,
}: {
  items: AppointmentItem[];
  conflicts: Set<string>;
  onSelect: (item: AppointmentItem) => void;
}) {
  const now = new Date();
  const buckets = useMemo(() => {
    const map = new Map<string, AppointmentItem[]>();
    for (const a of items) {
      const label = bucketLabel(new Date(a.scheduled_at), now);
      const arr = map.get(label) ?? [];
      arr.push(a);
      map.set(label, arr);
    }
    return BUCKET_ORDER.filter((b) => map.has(b)).map((b) => ({
      label: b,
      items: map.get(b)!,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  if (buckets.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
        <CalendarDays className="h-12 w-12 text-muted-foreground/30" />
        <div className="text-sm font-medium text-muted-foreground">Sin citas en este rango</div>
        <div className="text-xs text-muted-foreground">
          Crea una manualmente o espera a que el agente las agende.
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
      {buckets.map((b) => (
        <div key={b.label}>
          <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <CalendarDays className="h-3 w-3" />
            {b.label}
            <span className="font-normal">({b.items.length})</span>
          </div>
          <div className="space-y-1.5">
            {b.items.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => onSelect(a)}
                className="flex w-full items-start gap-3 rounded-lg border bg-card px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/50"
              >
                <div
                  className="mt-0.5 h-9 w-1 shrink-0 rounded-full"
                  style={{ backgroundColor: STATUS_COLOR[a.status] ?? "#6b7280" }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.customer_name ?? a.customer_phone}</span>
                    {conflicts.has(a.id) && (
                      <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                    )}
                    {a.created_by_type === "ai" && (
                      <Badge variant="outline" className="px-1 py-0 text-[10px]">
                        AI
                      </Badge>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(a.scheduled_at).toLocaleString("es-MX", {
                      weekday: "short",
                      day: "2-digit",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · {a.service}
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_BG[a.status] ?? ""}`}
                >
                  {STATUS_LABEL[a.status] ?? a.status}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Smart Input Panel ─────────────────────────────────────────────────────────

function SmartInputPanel({ onCreated }: { onCreated: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedApt | null>(null);
  const [customerId, setCustomerId] = useState("");
  const [customerQ, setCustomerQ] = useState("");
  const [conflicts, setConflicts] = useState<AppointmentConflict[]>([]);

  const customers = useQuery({
    queryKey: ["customers", "lookup", customerQ],
    queryFn: () => customersApi.list({ q: customerQ || undefined, limit: 20 }),
    enabled: customerQ.length > 1,
  });

  const create = useMutation({
    mutationFn: appointmentsApi.create,
    onSuccess: (data) => {
      if (data.conflicts.length > 0) {
        setConflicts(data.conflicts);
        toast.warning(`Cita creada con ${data.conflicts.length} conflicto(s)`);
      } else {
        toast.success("Cita creada");
        onCreated();
        setText("");
        setParsed(null);
        setCustomerId("");
        setCustomerQ("");
        setConflicts([]);
      }
      void qc.invalidateQueries({ queryKey: ["appointments"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.error("No se pudo crear", { description: e.message }),
  });

  function handleParse() {
    const result = parseSmartInput(text);
    setParsed(result);
    setConflicts([]);
  }

  function handleSubmit() {
    if (!parsed || !customerId) return;
    create.mutate({
      customer_id: customerId,
      scheduled_at: parsed.date.toISOString(),
      service: parsed.service,
    });
  }

  return (
    <div className="flex w-72 shrink-0 flex-col border-l bg-card">
      <div className="flex items-center gap-2 border-b px-3 py-2.5">
        <Sparkles className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">Nueva cita</span>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        <div>
          <Label className="text-xs">Describe la cita</Label>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"Mañana 4pm prueba de manejo"}
            rows={3}
            className="mt-1 resize-none text-sm"
          />
          <Button
            size="sm"
            variant="outline"
            className="mt-1.5 w-full text-xs"
            onClick={handleParse}
            disabled={!text.trim()}
          >
            <Sparkles className="mr-1.5 h-3 w-3" />
            Interpretar
          </Button>
        </div>

        {parsed && (
          <div className="space-y-1.5 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-primary">
              Interpretación
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Fecha</span>
              <span className="font-medium">
                {parsed.date.toLocaleDateString("es-MX", {
                  weekday: "short",
                  day: "numeric",
                  month: "short",
                })}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Hora</span>
              <span className="font-medium">{fmtTime(parsed.date)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Servicio</span>
              <span className="max-w-[140px] truncate text-right font-medium">{parsed.service}</span>
            </div>
          </div>
        )}

        <div>
          <Label className="text-xs">Cliente</Label>
          <Input
            value={customerQ}
            onChange={(e) => {
              setCustomerQ(e.target.value);
              if (e.target.value !== customerQ) setCustomerId("");
            }}
            placeholder="Buscar por nombre o tel."
            className="mt-1 text-xs"
          />
          {customerQ.length > 1 && (
            <div className="mt-1 max-h-36 overflow-y-auto rounded-md border">
              {(customers.data?.items ?? []).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => {
                    setCustomerId(c.id);
                    setCustomerQ(c.name ?? c.phone_e164);
                  }}
                  className={`flex w-full items-center justify-between px-2 py-1.5 text-xs hover:bg-muted ${customerId === c.id ? "bg-muted" : ""}`}
                >
                  <span>{c.name ?? "(sin nombre)"}</span>
                  <span className="text-muted-foreground">{c.phone_e164}</span>
                </button>
              ))}
              {customers.data?.items.length === 0 && (
                <div className="px-2 py-2 text-xs text-muted-foreground">Sin resultados</div>
              )}
            </div>
          )}
        </div>

        {conflicts.length > 0 && (
          <div className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs">
            <div className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" /> Conflictos detectados
            </div>
            {conflicts.map((c) => (
              <div key={c.id} className="text-amber-800 dark:text-amber-300">
                {new Date(c.scheduled_at).toLocaleString("es-MX", {
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}{" "}
                · {c.service}
              </div>
            ))}
          </div>
        )}

        <Button
          className="w-full"
          size="sm"
          onClick={handleSubmit}
          disabled={!parsed || !customerId || create.isPending}
        >
          {create.isPending ? "Creando..." : "Crear cita"}
        </Button>
      </div>
    </div>
  );
}

// ─── Appointment Detail Panel ──────────────────────────────────────────────────

function AppointmentDetailPanel({
  item,
  hasConflict,
  onClose,
  onUpdated,
  onDeleted,
}: {
  item: AppointmentItem;
  hasConflict: boolean;
  onClose: () => void;
  onUpdated: () => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [scheduledAt, setScheduledAt] = useState(toLocalInputValue(item.scheduled_at));
  const [service, setService] = useState(item.service);
  const [notes, setNotes] = useState(item.notes ?? "");
  const [statusValue, setStatusValue] = useState(item.status);

  const patchMut = useMutation({
    mutationFn: () =>
      appointmentsApi.patch(item.id, {
        scheduled_at: new Date(scheduledAt).toISOString(),
        service: service.trim(),
        status: statusValue,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Cita actualizada");
      void qc.invalidateQueries({ queryKey: ["appointments"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      setEditing(false);
      onUpdated();
    },
    onError: (e: Error) => toast.error("No se pudo actualizar", { description: e.message }),
  });

  const patchStatusMut = useMutation({
    mutationFn: (status: string) => appointmentsApi.patch(item.id, { status }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["appointments"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      onUpdated();
    },
    onError: (e: Error) => toast.error("No se pudo actualizar", { description: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: () => appointmentsApi.delete(item.id),
    onSuccess: () => {
      toast.success("Cita eliminada");
      void qc.invalidateQueries({ queryKey: ["appointments"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      onDeleted();
    },
    onError: (e: Error) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  const color = STATUS_COLOR[item.status] ?? "#6b7280";

  return (
    <div className="flex w-72 shrink-0 flex-col border-l bg-card">
      <div className="flex items-center justify-between border-b px-3 py-2.5">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {item.customer_name ?? item.customer_phone}
          </div>
          <div className="text-xs text-muted-foreground">{item.customer_phone}</div>
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7 shrink-0" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        <div className="flex flex-wrap gap-1.5">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => patchStatusMut.mutate(s)}
              disabled={patchStatusMut.isPending}
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-all ${
                item.status === s
                  ? STATUS_BG[s]
                  : "bg-muted/50 text-muted-foreground hover:bg-muted"
              }`}
            >
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>

        {hasConflict && (
          <div className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            Conflicto de horario detectado
          </div>
        )}

        {!editing ? (
          <div className="space-y-2.5">
            <div
              className="rounded-lg border-l-4 p-2.5"
              style={{ borderLeftColor: color }}
            >
              <div className="text-sm font-medium">{item.service}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {new Date(item.scheduled_at).toLocaleString("es-MX", {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </div>
              {item.notes && (
                <div className="mt-1.5 text-xs italic text-muted-foreground">{item.notes}</div>
              )}
            </div>

            <Badge variant="outline" className="text-[10px]">
              {item.created_by_type === "ai" ? "Creada por IA" : "Creada manualmente"}
            </Badge>
          </div>
        ) : (
          <div className="space-y-2.5">
            <div>
              <Label className="text-xs">Fecha y hora</Label>
              <Input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">Servicio</Label>
              <Input
                value={service}
                onChange={(e) => setService(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <Label className="text-xs">Estado</Label>
              <Select value={statusValue} onValueChange={setStatusValue}>
                <SelectTrigger className="mt-1 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s} value={s} className="text-xs">
                      {STATUS_LABEL[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Notas</Label>
              <Textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                className="mt-1 resize-none text-xs"
              />
            </div>
          </div>
        )}

        {item.conversation_id && (
          <Link
            to="/conversations/$conversationId"
            params={{ conversationId: item.conversation_id }}
            className="flex items-center gap-1.5 rounded-md border px-2.5 py-2 text-xs text-primary transition-colors hover:bg-muted"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Abrir conversación
          </Link>
        )}
      </div>

      <div className="flex items-center justify-between border-t px-3 py-2.5">
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7 text-destructive hover:text-destructive"
          onClick={() => {
            if (confirm("¿Eliminar esta cita?")) deleteMut.mutate();
          }}
          disabled={deleteMut.isPending}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setEditing(false)}
              >
                Cancelar
              </Button>
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={() => patchMut.mutate()}
                disabled={patchMut.isPending || !service.trim()}
              >
                {patchMut.isPending ? "Guardando..." : "Guardar"}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => setEditing(true)}
            >
              <Pencil className="mr-1.5 h-3 w-3" /> Editar
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

type ViewMode = "week" | "day" | "list";

export function AppointmentsPage() {
  const [view, setView] = useState<ViewMode>("week");
  const [weekStart, setWeekStart] = useState(() => getMondayOf(new Date()));
  const [dayDate, setDayDate] = useState(() => new Date());
  const [selected, setSelected] = useState<AppointmentItem | null>(null);
  const [showCreate, setShowCreate] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");

  const { dateFrom, dateTo } = useMemo(() => {
    if (view === "list") {
      const from = addDays(new Date(), -30);
      from.setHours(0, 0, 0, 0);
      const to = addDays(new Date(), 90);
      to.setHours(23, 59, 59, 999);
      return { dateFrom: from.toISOString(), dateTo: to.toISOString() };
    }
    if (view === "day") {
      const from = new Date(dayDate);
      from.setHours(0, 0, 0, 0);
      const to = new Date(dayDate);
      to.setHours(23, 59, 59, 999);
      return { dateFrom: from.toISOString(), dateTo: to.toISOString() };
    }
    const from = new Date(weekStart);
    const to = addDays(weekStart, 7);
    return { dateFrom: from.toISOString(), dateTo: to.toISOString() };
  }, [view, weekStart, dayDate]);

  const list = useQuery({
    queryKey: ["appointments", view, dateFrom, dateTo, statusFilter],
    queryFn: () =>
      appointmentsApi.list({
        date_from: dateFrom,
        date_to: dateTo,
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: 300,
      }),
  });

  const kpiQuery = useQuery({
    queryKey: ["appointments", "kpi"],
    queryFn: () => {
      const from = getMondayOf(new Date());
      const to = addDays(from, 7);
      return appointmentsApi.list({
        date_from: from.toISOString(),
        date_to: to.toISOString(),
        limit: 300,
      });
    },
    staleTime: 60_000,
  });

  const items = list.data?.items ?? [];
  const kpiItems = kpiQuery.data?.items ?? [];
  const conflicts = useMemo(() => detectConflicts(items), [items]);
  const kpiConflicts = useMemo(() => detectConflicts(kpiItems), [kpiItems]);

  const kpis = useMemo(() => {
    const now = new Date();
    return {
      thisWeek: kpiItems.length,
      today: kpiItems.filter((a) => isSameDay(new Date(a.scheduled_at), now)).length,
      conflicts: kpiConflicts.size,
      completed: kpiItems.filter((a) => a.status === "completed").length,
    };
  }, [kpiItems, kpiConflicts]);

  function prevPeriod() {
    if (view === "week") setWeekStart((d) => addDays(d, -7));
    else if (view === "day") setDayDate((d) => addDays(d, -1));
  }

  function nextPeriod() {
    if (view === "week") setWeekStart((d) => addDays(d, 7));
    else if (view === "day") setDayDate((d) => addDays(d, 1));
  }

  function goToday() {
    setWeekStart(getMondayOf(new Date()));
    setDayDate(new Date());
  }

  const periodLabel = useMemo(() => {
    if (view === "week") {
      return `${fmtShort(weekStart)} – ${fmtShort(addDays(weekStart, 6))}`;
    }
    if (view === "day") {
      return dayDate.toLocaleDateString("es-MX", {
        weekday: "short",
        day: "numeric",
        month: "long",
      });
    }
    return "";
  }, [view, weekStart, dayDate]);

  const rightPanel = selected ? "detail" : showCreate ? "create" : null;

  function handleSelect(item: AppointmentItem) {
    setSelected(item);
    setShowCreate(false);
  }

  function handleRefetch() {
    void list.refetch();
    void kpiQuery.refetch();
  }

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden">
      {/* Top bar */}
      <div className="shrink-0 space-y-3 border-b bg-card px-6 py-3">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold tracking-tight">Citas</h1>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setSelected(null);
                setShowCreate(true);
              }}
            >
              <CalendarPlus className="mr-1.5 h-3.5 w-3.5" /> Nueva cita
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              title="Configuración"
              onClick={() => setShowSettings(true)}
            >
              <Settings2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex gap-3 overflow-x-auto pb-0.5">
          <KPITile
            label="Esta semana"
            value={kpis.thisWeek}
            icon={CalendarDays}
            colorClass="bg-blue-500/10 text-blue-600 dark:text-blue-400"
          />
          <KPITile
            label="Hoy"
            value={kpis.today}
            icon={Clock}
            colorClass="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          />
          <KPITile
            label="Conflictos"
            value={kpis.conflicts}
            icon={AlertTriangle}
            colorClass={
              kpis.conflicts > 0
                ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                : "bg-muted text-muted-foreground"
            }
          />
          <KPITile
            label="Completadas"
            value={kpis.completed}
            icon={CalendarCheck}
            colorClass="bg-violet-500/10 text-violet-600 dark:text-violet-400"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex rounded-lg border bg-muted/40 p-0.5">
            {(
              [
                { id: "week", label: "Semana", icon: CalendarDays },
                { id: "day", label: "Día", icon: Clock },
                { id: "list", label: "Lista", icon: LayoutList },
              ] as const
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setView(id)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-all ${
                  view === id
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>

          {view !== "list" && (
            <div className="flex items-center gap-1">
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={prevPeriod}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="min-w-[140px] text-center text-sm font-medium">{periodLabel}</span>
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={nextPeriod}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="ml-1 h-7 text-xs"
                onClick={goToday}
              >
                Hoy
              </Button>
            </div>
          )}

          {view === "list" && (
            <div className="flex flex-wrap gap-1.5">
              {["all", ...STATUSES].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatusFilter(s)}
                  className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                    statusFilter === s
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {s === "all" ? "Todas" : STATUS_LABEL[s]}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 flex-col overflow-hidden">
          {list.isLoading ? (
            <div className="flex flex-1 flex-col gap-2 p-4">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          ) : view === "week" ? (
            <WeekView
              weekStart={weekStart}
              items={items}
              conflicts={conflicts}
              onSelect={handleSelect}
            />
          ) : view === "day" ? (
            <DayView
              date={dayDate}
              items={items}
              conflicts={conflicts}
              onSelect={handleSelect}
            />
          ) : (
            <ListView items={items} conflicts={conflicts} onSelect={handleSelect} />
          )}
        </div>

        {rightPanel === "detail" && selected && (
          <AppointmentDetailPanel
            key={selected.id}
            item={selected}
            hasConflict={conflicts.has(selected.id)}
            onClose={() => setSelected(null)}
            onUpdated={() => {
              handleRefetch();
              setSelected(null);
            }}
            onDeleted={() => {
              handleRefetch();
              setSelected(null);
            }}
          />
        )}
        {rightPanel === "create" && (
          <SmartInputPanel onCreated={handleRefetch} />
        )}
      </div>

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="relative max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-xl border bg-background shadow-xl">
            <AppointmentsFeatureSettings onClose={() => setShowSettings(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

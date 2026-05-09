import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  CalendarDays,
  CalendarPlus,
  Check,
  ExternalLink,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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

const STATUSES = ["scheduled", "completed", "cancelled", "no_show"] as const;
type AppointmentStatus = (typeof STATUSES)[number];

const STATUS_LABEL: Record<string, string> = {
  scheduled: "Programada",
  completed: "Completada",
  cancelled: "Cancelada",
  no_show: "No asistió",
};

const STATUS_BADGE: Record<string, string> = {
  scheduled: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  completed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  cancelled: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300",
  no_show: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function bucketLabel(scheduled: Date, now: Date): string {
  const today = startOfDay(now).getTime();
  const day = startOfDay(scheduled).getTime();
  const diffDays = Math.round((day - today) / 86_400_000);
  if (diffDays < 0) return "Pasadas";
  if (diffDays === 0) return "Hoy";
  if (diffDays === 1) return "Mañana";
  if (diffDays < 7) return "Próximos 7 días";
  if (diffDays < 30) return "Este mes";
  return "Más adelante";
}

const BUCKET_ORDER = ["Pasadas", "Hoy", "Mañana", "Próximos 7 días", "Este mes", "Más adelante"];

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("es-MX", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toLocalInputValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function AppointmentsPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<AppointmentStatus | "all">("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<AppointmentItem | null>(null);

  const list = useQuery({
    queryKey: ["appointments", statusFilter],
    queryFn: () =>
      appointmentsApi.list(
        statusFilter === "all" ? { limit: 200 } : { status: statusFilter, limit: 200 },
      ),
  });

  const patchMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: AppointmentStatus }) =>
      appointmentsApi.patch(id, { status }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: e.message }),
  });

  const removeMut = useMutation({
    mutationFn: appointmentsApi.delete,
    onSuccess: () => {
      toast.success("Cita eliminada");
      void qc.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (e) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: 0, scheduled: 0, completed: 0, cancelled: 0, no_show: 0 };
    for (const a of items) {
      c.all = (c.all ?? 0) + 1;
      c[a.status] = (c[a.status] ?? 0) + 1;
    }
    return c;
  }, [items]);

  const buckets = useMemo(() => {
    const now = new Date();
    const map = new Map<string, AppointmentItem[]>();
    for (const a of items) {
      const label = bucketLabel(new Date(a.scheduled_at), now);
      const arr = map.get(label) ?? [];
      arr.push(a);
      map.set(label, arr);
    }
    return BUCKET_ORDER.filter((b) => map.has(b)).map((b) => ({ label: b, items: map.get(b)! }));
  }, [items]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Citas</h1>
          <p className="text-sm text-muted-foreground">
            Agenda manual y citas creadas por el flujo conversacional.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <CalendarPlus className="mr-2 h-4 w-4" /> Nueva cita
            </Button>
          </DialogTrigger>
          <CreateAppointmentDialog onClose={() => setCreateOpen(false)} />
        </Dialog>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <FilterChip
          label="Todas"
          count={counts.all ?? 0}
          active={statusFilter === "all"}
          onClick={() => setStatusFilter("all")}
        />
        {STATUSES.map((s) => (
          <FilterChip
            key={s}
            label={STATUS_LABEL[s] ?? s}
            count={counts[s] ?? 0}
            active={statusFilter === s}
            onClick={() => setStatusFilter(s)}
          />
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          {items.length} de {total} citas
        </span>
      </div>

      {list.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : buckets.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <CalendarDays className="h-10 w-10 text-muted-foreground" />
            <div className="text-sm font-medium">Sin citas para este filtro</div>
            <div className="text-xs text-muted-foreground">
              Crea una manualmente o espera a que tu agente las agende.
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {buckets.map((b) => (
            <Card key={b.label}>
              <CardHeader className="py-3">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <CalendarDays className="h-4 w-4" /> {b.label}
                  <span className="text-xs text-muted-foreground">({b.items.length})</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 pt-0">
                {b.items.map((a) => (
                  <AppointmentRow
                    key={a.id}
                    item={a}
                    onEdit={() => setEditing(a)}
                    onComplete={() => patchMut.mutate({ id: a.id, status: "completed" })}
                    onCancel={() => patchMut.mutate({ id: a.id, status: "cancelled" })}
                    onDelete={() => {
                      if (confirm("¿Eliminar esta cita?")) removeMut.mutate(a.id);
                    }}
                  />
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {editing && (
        <EditAppointmentDialog
          appointment={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs transition-colors ${
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-background hover:bg-muted"
      }`}
    >
      {label} <span className="ml-1 opacity-70">{count}</span>
    </button>
  );
}

function AppointmentRow({
  item,
  onEdit,
  onComplete,
  onCancel,
  onDelete,
}: {
  item: AppointmentItem;
  onEdit: () => void;
  onComplete: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="grid items-center gap-2 rounded-md border p-3 text-sm md:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{item.customer_name ?? item.customer_phone}</span>
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_BADGE[item.status] ?? ""}`}>
            {STATUS_LABEL[item.status] ?? item.status}
          </span>
          {item.created_by_type === "ai" && (
            <Badge variant="outline" className="text-[10px]">AI</Badge>
          )}
          {item.conversation_id && (
            <Link
              to="/conversations/$conversationId"
              params={{ conversationId: item.conversation_id }}
              className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" /> conversación
            </Link>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {fmtDateTime(item.scheduled_at)} · {item.service}
        </div>
        {item.notes && (
          <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.notes}</div>
        )}
      </div>
      <div className="flex items-center gap-1 justify-self-end">
        {item.status === "scheduled" && (
          <>
            <Button size="icon" variant="ghost" title="Marcar completada" onClick={onComplete}>
              <Check className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" title="Cancelar" onClick={onCancel}>
              <X className="h-4 w-4" />
            </Button>
          </>
        )}
        <Button size="icon" variant="ghost" title="Editar" onClick={onEdit}>
          <Pencil className="h-4 w-4" />
        </Button>
        <Button size="icon" variant="ghost" title="Eliminar" onClick={onDelete}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function CreateAppointmentDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [service, setService] = useState("");
  const [notes, setNotes] = useState("");
  const [conflicts, setConflicts] = useState<AppointmentConflict[]>([]);

  const customers = useQuery({
    queryKey: ["customers", q],
    queryFn: () => customersApi.list({ q: q || undefined, limit: 20 }),
  });

  const create = useMutation({
    mutationFn: appointmentsApi.create,
    onSuccess: (data) => {
      if (data.conflicts.length > 0) {
        setConflicts(data.conflicts);
        toast.warning("Cita creada con conflictos", {
          description: `${data.conflicts.length} cita(s) cercana(s) para el mismo cliente.`,
        });
      } else {
        toast.success("Cita creada");
        onClose();
      }
      void qc.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (e) => toast.error("No se pudo crear", { description: e.message }),
  });

  const submit = () => {
    if (!customerId || !scheduledAt || !service.trim()) return;
    create.mutate({
      customer_id: customerId,
      scheduled_at: new Date(scheduledAt).toISOString(),
      service: service.trim(),
      notes: notes.trim() || null,
    });
  };

  return (
    <DialogContent className="max-w-lg">
      <DialogHeader>
        <DialogTitle>Nueva cita</DialogTitle>
      </DialogHeader>
      <div className="space-y-3">
        <div>
          <Label>Cliente</Label>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por nombre o teléfono" />
          <div className="mt-2 max-h-40 space-y-1 overflow-auto rounded-md border p-1">
            {(customers.data?.items ?? []).map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setCustomerId(c.id);
                  setQ(c.name ?? c.phone_e164);
                }}
                className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs hover:bg-muted ${
                  customerId === c.id ? "bg-muted" : ""
                }`}
              >
                <span>{c.name ?? "(sin nombre)"}</span>
                <span className="text-muted-foreground">{c.phone_e164}</span>
              </button>
            ))}
            {customers.data?.items.length === 0 && (
              <div className="px-2 py-2 text-xs text-muted-foreground">Sin resultados</div>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Fecha y hora</Label>
            <Input
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
            />
          </div>
          <div>
            <Label>Servicio</Label>
            <Input value={service} onChange={(e) => setService(e.target.value)} placeholder="Prueba de manejo" />
          </div>
        </div>
        <div>
          <Label>Notas</Label>
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </div>
        {conflicts.length > 0 && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
            <div className="mb-1 flex items-center gap-1 font-medium text-amber-700 dark:text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" /> Conflictos detectados
            </div>
            <ul className="space-y-0.5 text-amber-800 dark:text-amber-300">
              {conflicts.map((c) => (
                <li key={c.id}>
                  {fmtDateTime(c.scheduled_at)} · {c.service}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cerrar
        </Button>
        <Button
          onClick={submit}
          disabled={create.isPending || !customerId || !scheduledAt || !service.trim()}
        >
          {create.isPending ? "Creando..." : "Crear cita"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function EditAppointmentDialog({
  appointment,
  onClose,
}: {
  appointment: AppointmentItem;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [scheduledAt, setScheduledAt] = useState(toLocalInputValue(appointment.scheduled_at));
  const [service, setService] = useState(appointment.service);
  const [statusValue, setStatusValue] = useState<AppointmentStatus>(appointment.status as AppointmentStatus);
  const [notes, setNotes] = useState(appointment.notes ?? "");

  const patch = useMutation({
    mutationFn: () =>
      appointmentsApi.patch(appointment.id, {
        scheduled_at: new Date(scheduledAt).toISOString(),
        service: service.trim(),
        status: statusValue,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      toast.success("Cita actualizada");
      void qc.invalidateQueries({ queryKey: ["appointments"] });
      onClose();
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: e.message }),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Editar cita</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-md border bg-muted/50 px-3 py-2 text-xs">
            <div className="font-medium">{appointment.customer_name ?? appointment.customer_phone}</div>
            <div className="text-muted-foreground">{appointment.customer_phone}</div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Fecha y hora</Label>
              <Input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
              />
            </div>
            <div>
              <Label>Estado</Label>
              <Select value={statusValue} onValueChange={(v) => setStatusValue(v as AppointmentStatus)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {STATUS_LABEL[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>Servicio</Label>
            <Input value={service} onChange={(e) => setService(e.target.value)} />
          </div>
          <div>
            <Label>Notas</Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cerrar
          </Button>
          <Button onClick={() => patch.mutate()} disabled={patch.isPending || !service.trim()}>
            {patch.isPending ? "Guardando..." : "Guardar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

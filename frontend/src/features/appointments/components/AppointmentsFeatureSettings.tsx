import {
  AlertTriangle,
  Bell,
  CalendarDays,
  Check,
  Clock,
  FileText,
  Link2,
  MessageCircle,
  Settings,
  Shield,
  Sparkles,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { Textarea } from "@/components/ui/textarea";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface AptSettings {
  scheduling: {
    defaultDuration: number;
    workdayStart: string;
    workdayEnd: string;
    workdays: number[]; // 0=Sun..6=Sat
    bufferMinutes: number;
  };
  smartParser: {
    enabled: boolean;
    defaultService: string;
  };
  conflicts: {
    enabled: boolean;
    thresholdHours: number;
    blockCreation: boolean;
  };
  statusWorkflow: {
    allowedTransitions: Record<string, string[]>;
  };
  calendarViews: {
    defaultView: "week" | "day" | "list";
    showWeekends: boolean;
  };
  emptyStates: {
    noAppointmentsMessage: string;
    noTodayMessage: string;
  };
  whatsapp: {
    autoLink: boolean;
    confirmationMessage: string;
    reminderMessage: string;
  };
  notifications: {
    remind24h: boolean;
    remind1h: boolean;
    remindChannel: "whatsapp" | "email" | "none";
  };
  permissions: {
    canCreate: string[];
    canEdit: string[];
    canDelete: string[];
  };
  audit: {
    logChanges: boolean;
    retentionDays: number;
  };
}

const STORAGE_KEY = "atendia_apt_settings";

const DEFAULTS: AptSettings = {
  scheduling: {
    defaultDuration: 30,
    workdayStart: "09:00",
    workdayEnd: "18:00",
    workdays: [1, 2, 3, 4, 5],
    bufferMinutes: 0,
  },
  smartParser: {
    enabled: true,
    defaultService: "Prueba de manejo",
  },
  conflicts: {
    enabled: true,
    thresholdHours: 2,
    blockCreation: false,
  },
  statusWorkflow: {
    allowedTransitions: {
      scheduled: ["completed", "cancelled", "no_show"],
      completed: [],
      cancelled: ["scheduled"],
      no_show: ["scheduled"],
    },
  },
  calendarViews: {
    defaultView: "week",
    showWeekends: true,
  },
  emptyStates: {
    noAppointmentsMessage: "Sin citas para este período.",
    noTodayMessage: "Sin citas para hoy.",
  },
  whatsapp: {
    autoLink: true,
    confirmationMessage:
      "Hola {{nombre}}, tu cita de {{servicio}} está confirmada para el {{fecha}} a las {{hora}}.",
    reminderMessage: "Recordatorio: tu cita de {{servicio}} es mañana a las {{hora}}.",
  },
  notifications: {
    remind24h: true,
    remind1h: true,
    remindChannel: "whatsapp",
  },
  permissions: {
    canCreate: ["agent", "tenant_admin", "superadmin"],
    canEdit: ["tenant_admin", "superadmin"],
    canDelete: ["tenant_admin", "superadmin"],
  },
  audit: {
    logChanges: true,
    retentionDays: 90,
  },
};

function loadSettings(): AptSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) } as AptSettings;
  } catch {
    // ignore
  }
  return DEFAULTS;
}

// ─── Module config ─────────────────────────────────────────────────────────────

const MODULES = [
  { id: "scheduling", label: "Programación", icon: CalendarDays },
  { id: "smartParser", label: "Parser inteligente", icon: Sparkles },
  { id: "conflicts", label: "Conflictos", icon: AlertTriangle },
  { id: "statusWorkflow", label: "Flujo de estados", icon: Zap },
  { id: "calendarViews", label: "Vistas de calendario", icon: Clock },
  { id: "emptyStates", label: "Estados vacíos", icon: FileText },
  { id: "whatsapp", label: "WhatsApp", icon: MessageCircle },
  { id: "notifications", label: "Notificaciones", icon: Bell },
  { id: "permissions", label: "Permisos", icon: Shield },
  { id: "audit", label: "Auditoría", icon: FileText },
] as const;

type ModuleId = (typeof MODULES)[number]["id"];

const ALL_STATUSES = ["scheduled", "completed", "cancelled", "no_show"] as const;
const STATUS_LABEL: Record<string, string> = {
  scheduled: "Programada",
  completed: "Completada",
  cancelled: "Cancelada",
  no_show: "No asistió",
};
const ROLES = ["agent", "tenant_admin", "superadmin"] as const;
const ROLE_LABEL: Record<string, string> = {
  agent: "Agente",
  tenant_admin: "Admin tenant",
  superadmin: "Superadmin",
};
const WEEKDAY_LABELS = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

// ─── Toggle ────────────────────────────────────────────────────────────────────

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
        checked ? "bg-primary" : "bg-muted-foreground/30"
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-4" : "translate-x-0"
        }`}
      />
    </button>
  );
}

// ─── Checkbox row ──────────────────────────────────────────────────────────────

function CheckRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2 text-sm"
    >
      <div
        className={`grid h-4 w-4 place-items-center rounded border transition-colors ${
          checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background"
        }`}
      >
        {checked && <Check className="h-3 w-3" />}
      </div>
      {label}
    </button>
  );
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <Label className="text-sm font-normal text-muted-foreground">{label}</Label>
      <div className="w-48 shrink-0">{children}</div>
    </div>
  );
}

// ─── Module panels ─────────────────────────────────────────────────────────────

function SchedulingPanel({
  s,
  onChange,
}: {
  s: AptSettings["scheduling"];
  onChange: (v: AptSettings["scheduling"]) => void;
}) {
  return (
    <Section title="Programación de citas">
      <FieldRow label="Duración por defecto (min)">
        <Select
          value={String(s.defaultDuration)}
          onValueChange={(v) => onChange({ ...s, defaultDuration: Number(v) })}
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[15, 30, 45, 60, 90, 120].map((d) => (
              <SelectItem key={d} value={String(d)}>
                {d} min
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FieldRow>

      <FieldRow label="Inicio jornada">
        <Input
          type="time"
          value={s.workdayStart}
          onChange={(e) => onChange({ ...s, workdayStart: e.target.value })}
          className="text-sm"
        />
      </FieldRow>

      <FieldRow label="Fin jornada">
        <Input
          type="time"
          value={s.workdayEnd}
          onChange={(e) => onChange({ ...s, workdayEnd: e.target.value })}
          className="text-sm"
        />
      </FieldRow>

      <FieldRow label="Buffer entre citas (min)">
        <Input
          type="number"
          min={0}
          max={60}
          step={5}
          value={s.bufferMinutes}
          onChange={(e) => onChange({ ...s, bufferMinutes: Number(e.target.value) })}
          className="text-sm"
        />
      </FieldRow>

      <div className="space-y-2">
        <Label className="text-sm font-normal text-muted-foreground">Días hábiles</Label>
        <div className="flex gap-2">
          {WEEKDAY_LABELS.map((day, i) => (
            <button
              key={i}
              type="button"
              onClick={() => {
                const days = s.workdays.includes(i)
                  ? s.workdays.filter((d) => d !== i)
                  : [...s.workdays, i];
                onChange({ ...s, workdays: days });
              }}
              className={`h-8 w-8 rounded-full text-xs font-medium transition-colors ${
                s.workdays.includes(i)
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted-foreground/20"
              }`}
            >
              {day}
            </button>
          ))}
        </div>
      </div>
    </Section>
  );
}

function SmartParserPanel({
  s,
  onChange,
}: {
  s: AptSettings["smartParser"];
  onChange: (v: AptSettings["smartParser"]) => void;
}) {
  return (
    <Section title="Parser inteligente">
      <FieldRow label="Activar parser">
        <div className="flex justify-end">
          <Toggle checked={s.enabled} onChange={(v) => onChange({ ...s, enabled: v })} />
        </div>
      </FieldRow>
      <FieldRow label="Servicio por defecto">
        <Input
          value={s.defaultService}
          onChange={(e) => onChange({ ...s, defaultService: e.target.value })}
          placeholder="Prueba de manejo"
          className="text-sm"
          disabled={!s.enabled}
        />
      </FieldRow>
      <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
        El parser convierte texto como "Mañana 4pm prueba de manejo" en una cita estructurada. Soporta
        expresiones de día (hoy, mañana, lunes…), hora (am/pm, 24h) y servicio libre.
      </div>
    </Section>
  );
}

function ConflictsPanel({
  s,
  onChange,
}: {
  s: AptSettings["conflicts"];
  onChange: (v: AptSettings["conflicts"]) => void;
}) {
  return (
    <Section title="Detección de conflictos">
      <FieldRow label="Activar detección">
        <div className="flex justify-end">
          <Toggle checked={s.enabled} onChange={(v) => onChange({ ...s, enabled: v })} />
        </div>
      </FieldRow>
      <FieldRow label="Umbral de conflicto (horas)">
        <Select
          value={String(s.thresholdHours)}
          onValueChange={(v) => onChange({ ...s, thresholdHours: Number(v) })}
          disabled={!s.enabled}
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[1, 2, 4, 8, 24].map((h) => (
              <SelectItem key={h} value={String(h)}>
                {h}h
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FieldRow>
      <FieldRow label="Bloquear creación con conflicto">
        <div className="flex justify-end">
          <Toggle
            checked={s.blockCreation}
            onChange={(v) => onChange({ ...s, blockCreation: v })}
          />
        </div>
      </FieldRow>
    </Section>
  );
}

function StatusWorkflowPanel({
  s,
  onChange,
}: {
  s: AptSettings["statusWorkflow"];
  onChange: (v: AptSettings["statusWorkflow"]) => void;
}) {
  function toggle(from: string, to: string) {
    const current = s.allowedTransitions[from] ?? [];
    const updated = current.includes(to) ? current.filter((x) => x !== to) : [...current, to];
    onChange({ ...s, allowedTransitions: { ...s.allowedTransitions, [from]: updated } });
  }

  return (
    <Section title="Flujo de estados permitidos">
      <div className="text-xs text-muted-foreground">
        Define qué transiciones de estado están permitidas.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="pb-2 pr-3 text-left font-medium text-muted-foreground">Desde →</th>
              {ALL_STATUSES.map((s) => (
                <th key={s} className="pb-2 px-2 text-center font-medium text-muted-foreground">
                  {STATUS_LABEL[s]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ALL_STATUSES.map((from) => (
              <tr key={from} className="border-t">
                <td className="py-2 pr-3 font-medium">{STATUS_LABEL[from]}</td>
                {ALL_STATUSES.map((to) => (
                  <td key={to} className="px-2 py-2 text-center">
                    {from === to ? (
                      <span className="text-muted-foreground/40">—</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => toggle(from, to)}
                        className={`mx-auto grid h-5 w-5 place-items-center rounded border transition-colors ${
                          (s.allowedTransitions[from] ?? []).includes(to)
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-background hover:bg-muted"
                        }`}
                      >
                        {(s.allowedTransitions[from] ?? []).includes(to) && (
                          <Check className="h-3 w-3" />
                        )}
                      </button>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function CalendarViewsPanel({
  s,
  onChange,
}: {
  s: AptSettings["calendarViews"];
  onChange: (v: AptSettings["calendarViews"]) => void;
}) {
  return (
    <Section title="Vistas de calendario">
      <FieldRow label="Vista por defecto">
        <Select
          value={s.defaultView}
          onValueChange={(v) =>
            onChange({ ...s, defaultView: v as AptSettings["calendarViews"]["defaultView"] })
          }
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="week">Semana</SelectItem>
            <SelectItem value="day">Día</SelectItem>
            <SelectItem value="list">Lista</SelectItem>
          </SelectContent>
        </Select>
      </FieldRow>
      <FieldRow label="Mostrar fines de semana">
        <div className="flex justify-end">
          <Toggle
            checked={s.showWeekends}
            onChange={(v) => onChange({ ...s, showWeekends: v })}
          />
        </div>
      </FieldRow>
    </Section>
  );
}

function EmptyStatesPanel({
  s,
  onChange,
}: {
  s: AptSettings["emptyStates"];
  onChange: (v: AptSettings["emptyStates"]) => void;
}) {
  return (
    <Section title="Mensajes de estado vacío">
      <div className="space-y-3">
        <div>
          <Label className="text-sm font-normal text-muted-foreground">Sin citas (general)</Label>
          <Textarea
            value={s.noAppointmentsMessage}
            onChange={(e) => onChange({ ...s, noAppointmentsMessage: e.target.value })}
            rows={2}
            className="mt-1 resize-none text-sm"
          />
        </div>
        <div>
          <Label className="text-sm font-normal text-muted-foreground">Sin citas para hoy</Label>
          <Textarea
            value={s.noTodayMessage}
            onChange={(e) => onChange({ ...s, noTodayMessage: e.target.value })}
            rows={2}
            className="mt-1 resize-none text-sm"
          />
        </div>
      </div>
    </Section>
  );
}

function WhatsAppPanel({
  s,
  onChange,
}: {
  s: AptSettings["whatsapp"];
  onChange: (v: AptSettings["whatsapp"]) => void;
}) {
  return (
    <Section title="Integración WhatsApp">
      <FieldRow label="Vincular automáticamente a conversación">
        <div className="flex justify-end">
          <Toggle checked={s.autoLink} onChange={(v) => onChange({ ...s, autoLink: v })} />
        </div>
      </FieldRow>
      <div className="space-y-3">
        <div>
          <Label className="text-sm font-normal text-muted-foreground">
            Mensaje de confirmación
          </Label>
          <div className="mt-0.5 text-xs text-muted-foreground">
            Variables: {"{{nombre}}"}, {"{{servicio}}"}, {"{{fecha}}"}, {"{{hora}}"}
          </div>
          <Textarea
            value={s.confirmationMessage}
            onChange={(e) => onChange({ ...s, confirmationMessage: e.target.value })}
            rows={3}
            className="mt-1 resize-none text-sm"
          />
        </div>
        <div>
          <Label className="text-sm font-normal text-muted-foreground">
            Mensaje de recordatorio
          </Label>
          <Textarea
            value={s.reminderMessage}
            onChange={(e) => onChange({ ...s, reminderMessage: e.target.value })}
            rows={3}
            className="mt-1 resize-none text-sm"
          />
        </div>
      </div>
    </Section>
  );
}

function NotificationsPanel({
  s,
  onChange,
}: {
  s: AptSettings["notifications"];
  onChange: (v: AptSettings["notifications"]) => void;
}) {
  return (
    <Section title="Notificaciones y recordatorios">
      <FieldRow label="Recordatorio 24h antes">
        <div className="flex justify-end">
          <Toggle checked={s.remind24h} onChange={(v) => onChange({ ...s, remind24h: v })} />
        </div>
      </FieldRow>
      <FieldRow label="Recordatorio 1h antes">
        <div className="flex justify-end">
          <Toggle checked={s.remind1h} onChange={(v) => onChange({ ...s, remind1h: v })} />
        </div>
      </FieldRow>
      <FieldRow label="Canal de recordatorio">
        <Select
          value={s.remindChannel}
          onValueChange={(v) =>
            onChange({
              ...s,
              remindChannel: v as AptSettings["notifications"]["remindChannel"],
            })
          }
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="whatsapp">WhatsApp</SelectItem>
            <SelectItem value="email">Email</SelectItem>
            <SelectItem value="none">Desactivado</SelectItem>
          </SelectContent>
        </Select>
      </FieldRow>
    </Section>
  );
}

function PermissionsPanel({
  s,
  onChange,
}: {
  s: AptSettings["permissions"];
  onChange: (v: AptSettings["permissions"]) => void;
}) {
  function toggleRole(field: keyof AptSettings["permissions"], role: string) {
    const current = s[field];
    const updated = current.includes(role)
      ? current.filter((r) => r !== role)
      : [...current, role];
    onChange({ ...s, [field]: updated });
  }

  return (
    <Section title="Permisos por rol">
      <div className="space-y-4 text-sm">
        {(
          [
            { field: "canCreate" as const, label: "Crear citas" },
            { field: "canEdit" as const, label: "Editar citas" },
            { field: "canDelete" as const, label: "Eliminar citas" },
          ] as const
        ).map(({ field, label }) => (
          <div key={field}>
            <div className="mb-2 text-sm font-normal text-muted-foreground">{label}</div>
            <div className="flex flex-wrap gap-3">
              {ROLES.map((role) => (
                <CheckRow
                  key={role}
                  label={ROLE_LABEL[role] ?? role}
                  checked={s[field].includes(role)}
                  onChange={() => toggleRole(field, role)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function AuditPanel({
  s,
  onChange,
}: {
  s: AptSettings["audit"];
  onChange: (v: AptSettings["audit"]) => void;
}) {
  return (
    <Section title="Auditoría">
      <FieldRow label="Registrar cambios">
        <div className="flex justify-end">
          <Toggle
            checked={s.logChanges}
            onChange={(v) => onChange({ ...s, logChanges: v })}
          />
        </div>
      </FieldRow>
      <FieldRow label="Retención (días)">
        <Select
          value={String(s.retentionDays)}
          onValueChange={(v) => onChange({ ...s, retentionDays: Number(v) })}
          disabled={!s.logChanges}
        >
          <SelectTrigger className="text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[30, 60, 90, 180, 365].map((d) => (
              <SelectItem key={d} value={String(d)}>
                {d} días
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FieldRow>
    </Section>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function AppointmentsFeatureSettings({ onClose }: { onClose: () => void }) {
  const [activeModule, setActiveModule] = useState<ModuleId>("scheduling");
  const [settings, setSettings] = useState<AptSettings>(loadSettings);
  const [dirty, setDirty] = useState(false);

  function update<K extends keyof AptSettings>(key: K, value: AptSettings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  function handleSave() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
      setDirty(false);
      toast.success("Configuración guardada");
    } catch {
      toast.error("No se pudo guardar");
    }
  }

  function handleReset() {
    if (!confirm("¿Restaurar configuración por defecto?")) return;
    setSettings(DEFAULTS);
    setDirty(true);
  }

  const activeIcon = MODULES.find((m) => m.id === activeModule);

  return (
    <div className="flex h-full max-h-[90vh] flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div className="flex items-center gap-2">
          <Settings className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-base font-semibold">Configuración de Citas</h2>
        </div>
        <Button size="icon" variant="ghost" className="h-8 w-8" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className="w-52 shrink-0 overflow-y-auto border-r bg-muted/20 py-3">
          {MODULES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveModule(id)}
              className={`flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm transition-colors ${
                activeModule === id
                  ? "bg-background font-medium text-foreground"
                  : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </button>
          ))}
        </div>

        {/* Panel */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {activeModule === "scheduling" && (
            <SchedulingPanel s={settings.scheduling} onChange={(v) => update("scheduling", v)} />
          )}
          {activeModule === "smartParser" && (
            <SmartParserPanel
              s={settings.smartParser}
              onChange={(v) => update("smartParser", v)}
            />
          )}
          {activeModule === "conflicts" && (
            <ConflictsPanel s={settings.conflicts} onChange={(v) => update("conflicts", v)} />
          )}
          {activeModule === "statusWorkflow" && (
            <StatusWorkflowPanel
              s={settings.statusWorkflow}
              onChange={(v) => update("statusWorkflow", v)}
            />
          )}
          {activeModule === "calendarViews" && (
            <CalendarViewsPanel
              s={settings.calendarViews}
              onChange={(v) => update("calendarViews", v)}
            />
          )}
          {activeModule === "emptyStates" && (
            <EmptyStatesPanel
              s={settings.emptyStates}
              onChange={(v) => update("emptyStates", v)}
            />
          )}
          {activeModule === "whatsapp" && (
            <WhatsAppPanel s={settings.whatsapp} onChange={(v) => update("whatsapp", v)} />
          )}
          {activeModule === "notifications" && (
            <NotificationsPanel
              s={settings.notifications}
              onChange={(v) => update("notifications", v)}
            />
          )}
          {activeModule === "permissions" && (
            <PermissionsPanel
              s={settings.permissions}
              onChange={(v) => update("permissions", v)}
            />
          )}
          {activeModule === "audit" && (
            <AuditPanel s={settings.audit} onChange={(v) => update("audit", v)} />
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t px-6 py-3">
        <Button size="sm" variant="ghost" className="text-xs text-muted-foreground" onClick={handleReset}>
          Restaurar por defecto
        </Button>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-muted-foreground">Cambios sin guardar</span>}
          <Button size="sm" variant="outline" onClick={onClose}>
            Cerrar
          </Button>
          <Button size="sm" onClick={handleSave} disabled={!dirty}>
            Guardar
          </Button>
        </div>
      </div>
    </div>
  );
}

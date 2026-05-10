/**
 * CustomerDetail — página de detalle de contacto AtendIA v2
 *
 * Diseño denso estilo operador (similar a Linear/Height):
 *  - Sub-header con back + overflow
 *  - Identidad del contacto + chips + acciones rápidas
 *  - Grid 2-col: área principal (izquierda) + columna meta (derecha)
 *  - Sección documentos + campos personalizados + notas
 *
 * Los campos que aún no existen en la API (automation, alerts, docs, etc.)
 * se sirven desde MOCK_OVERLAY hasta que el backend los exponga.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BotMessageSquare,
  BrainCircuit,
  Briefcase,
  Calendar,
  CalendarClock,
  Check,
  CheckSquare,
  ChevronRight,
  Copy,
  DollarSign,
  FileText,
  Globe,
  Info,
  Lock,
  MapPin,
  MessageCircle,
  MoreHorizontal,
  Pause,
  Pencil,
  Phone,
  Plus,
  Send,
  Sparkles,
  StickyNote,
  Tag,
  User,
  UserCheck,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  type CustomerNote,
  customersApi,
  notesApi,
} from "@/features/customers/api";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// Types for mock overlay (fields not yet in the API)
// ─────────────────────────────────────────────────────────────────────────────

type ScoreLevel = "Alto" | "Medio" | "Bajo";
type RiskLevel = "Alto" | "Medio" | "Bajo";
type DocStatus = "pendiente" | "completo" | "rechazado";
type ActivityType = "whatsapp" | "system" | "human";

interface ActivityItem {
  time: string;
  event: string;
  type: ActivityType;
}

interface DocItem {
  label: string;
  status: DocStatus;
}

// ─────────────────────────────────────────────────────────────────────────────
// Mock overlay — augments real API data until backend exposes these fields
// ─────────────────────────────────────────────────────────────────────────────

const MOCK: {
  scoreLevel: ScoreLevel;
  scoreReasons: string;
  chips: { label: string; icon: React.ComponentType<{ className?: string }> }[];
  lastMessage: { preview: string; time: string };
  source: string;
  advisor: { name: string; initials: string };
  activity: ActivityItem[];
  automation: { active: boolean; botName: string };
  alerts: string[];
  followUp: { datetime: string; note: string } | null;
  abandonmentRisk: { level: RiskLevel; lastResponseAgo: string };
  blockingReason: string | null;
  documents: DocItem[];
  customFieldSuggestions: string[];
  aiSummary: string;
  nextAction: string;
} = {
  scoreLevel: "Alto",
  scoreReasons: "Nómina + respondió hoy + etapa PLAN",
  chips: [
    { label: "10% Enganche", icon: DollarSign },
    { label: "Nómina tarjeta", icon: Briefcase },
    { label: "Interés: U5", icon: Tag },
    { label: "Nuevo León", icon: MapPin },
  ],
  lastMessage: {
    preview: "Sí, me interesa con 10% de enganche",
    time: "Hace 12 min",
  },
  source: "Facebook Ads · Campaña Nómina NL",
  advisor: { name: "Francisco Esparza", initials: "FE" },
  activity: [
    { time: "10:42", event: "Respondió WhatsApp", type: "whatsapp" },
    { time: "10:38", event: "Se envió catálogo", type: "system" },
    { time: "10:31", event: "Lead creado desde Meta Ads", type: "system" },
  ],
  automation: { active: true, botName: "Recepcionist" },
  alerts: [
    "Falta definir tipo de crédito",
    "No hay checklist asignado",
    "Sin seguimiento programado",
  ],
  followUp: { datetime: "Hoy 6:30 PM", note: "Pedir documentos faltantes" },
  abandonmentRisk: { level: "Medio", lastResponseAgo: "18 h" },
  blockingReason: "No ha enviado documentos",
  documents: [
    { label: "INE", status: "pendiente" },
    { label: "Comprobante", status: "pendiente" },
    { label: "Estados de cuenta", status: "pendiente" },
    { label: "Recibos", status: "pendiente" },
  ],
  customFieldSuggestions: [
    "Tipo de crédito",
    "Plan de enganche",
    "Modelo de interés",
    "Antigüedad laboral",
  ],
  aiSummary:
    "Cliente interesado en plan 10%. Falta confirmar tipo de ingreso y enviar requisitos.",
  nextAction: "Enviar requisitos de nómina tarjeta",
};

// ─────────────────────────────────────────────────────────────────────────────
// Tiny helpers
// ─────────────────────────────────────────────────────────────────────────────

function initials(name: string | null, phone: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return parts.length >= 2
      ? ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase()
      : (parts[0]?.slice(0, 2) ?? "").toUpperCase();
  }
  return phone.slice(-2);
}

function scoreLevelColor(level: ScoreLevel): string {
  return level === "Alto"
    ? "text-emerald-500"
    : level === "Medio"
      ? "text-amber-500"
      : "text-red-500";
}

function riskLevelColor(level: RiskLevel): string {
  return level === "Alto"
    ? "text-red-500"
    : level === "Medio"
      ? "text-amber-500"
      : "text-emerald-500";
}

function docStatusCn(status: DocStatus): string {
  return status === "completo"
    ? "bg-emerald-500/15 text-emerald-600 border-emerald-500/20"
    : status === "rechazado"
      ? "bg-red-500/15 text-red-600 border-red-500/20"
      : "bg-amber-500/15 text-amber-600 border-amber-500/20";
}

function activityDotCn(type: ActivityType): string {
  return type === "whatsapp"
    ? "bg-emerald-500"
    : type === "human"
      ? "bg-blue-500"
      : "bg-muted-foreground/40";
}

// ─────────────────────────────────────────────────────────────────────────────
// CircularScore — SVG ring progress
// ─────────────────────────────────────────────────────────────────────────────

function CircularScore({ value }: { value: number }) {
  const r = 26;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(100, Math.max(0, value)) / 100) * circ;

  return (
    <div className="relative flex h-16 w-16 shrink-0 items-center justify-center">
      <svg
        width="64"
        height="64"
        viewBox="0 0 64 64"
        className="-rotate-90"
        aria-hidden="true"
      >
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          strokeWidth="5"
          className="stroke-muted"
        />
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          className="stroke-emerald-500 transition-[stroke-dashoffset] duration-700"
        />
      </svg>
      <span className="absolute text-sm font-bold tabular-nums">{value}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// StatusBadge
// ─────────────────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const isActive = status === "Activa";
  const isInactive = status === "Inactiva";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
        isActive && "border-emerald-500/20 bg-emerald-500/10 text-emerald-600",
        isInactive && "border-border bg-muted text-muted-foreground",
        !isActive && !isInactive && "border-red-500/20 bg-red-500/10 text-red-600",
      )}
    >
      {isActive && (
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      )}
      {status}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EmptyState
// ─────────────────────────────────────────────────────────────────────────────

function EmptyState({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  hint: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
        <Icon className="h-5 w-5 text-muted-foreground" />
      </div>
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      {action && (
        <Button size="sm" className="mt-1" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SCard — dense Card with controllable padding (overrides shadcn defaults)
// ─────────────────────────────────────────────────────────────────────────────

function SCard({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border border-border bg-card text-card-foreground",
        className,
      )}
    >
      {children}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CopyBtn — icon button that copies text to clipboard
// ─────────────────────────────────────────────────────────────────────────────

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }
  return (
    <button
      type="button"
      aria-label="Copiar"
      onClick={handleCopy}
      className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FollowUpDialog
// ─────────────────────────────────────────────────────────────────────────────

function FollowUpDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [note, setNote] = useState("");

  function handleSave() {
    toast.success("Seguimiento programado");
    onClose();
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Programar seguimiento</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Fecha</label>
              <Input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="text-sm"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">Hora</label>
              <Input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="text-sm"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Nota</label>
            <Textarea
              rows={2}
              placeholder="¿Qué debes hacer en este seguimiento?"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="resize-none text-sm"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancelar
          </Button>
          <Button size="sm" onClick={handleSave}>
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NewNoteDialog
// ─────────────────────────────────────────────────────────────────────────────

function NewNoteDialog({
  open,
  onClose,
  customerId,
}: {
  open: boolean;
  onClose: () => void;
  customerId: string;
}) {
  const qc = useQueryClient();
  const [content, setContent] = useState("");
  const create = useMutation({
    mutationFn: () => notesApi.create(customerId, { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-notes", customerId] });
      toast.success("Nota guardada");
      setContent("");
      onClose();
    },
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Nueva nota</DialogTitle>
        </DialogHeader>
        <div className="py-2">
          <Textarea
            rows={4}
            autoFocus
            placeholder="Escribe una nota sobre este contacto…"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="resize-none text-sm"
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            size="sm"
            disabled={!content.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Guardar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CustomFieldsDialog
// ─────────────────────────────────────────────────────────────────────────────

function CustomFieldsDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Campos personalizados</DialogTitle>
        </DialogHeader>
        <div className="py-4">
          <EmptyState
            icon={Sparkles}
            title="Próximamente"
            hint="La configuración de campos personalizados estará disponible en Ajustes."
          />
        </div>
        <DialogFooter>
          <Button size="sm" onClick={onClose}>
            Entendido
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ContactIdentity
// ─────────────────────────────────────────────────────────────────────────────

function ContactIdentity({
  name,
  phone,
  status,
}: {
  name: string | null;
  phone: string;
  status: string;
}) {
  const abbr = initials(name, phone);

  return (
    <div className="flex flex-wrap items-start gap-4">
      {/* Avatar */}
      <Avatar className="h-14 w-14 shrink-0 text-base">
        <AvatarFallback className="bg-primary/15 text-primary font-semibold">
          {abbr}
        </AvatarFallback>
      </Avatar>

      {/* Identity */}
      <div className="flex flex-col gap-1.5 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold leading-none">
            {name ?? phone}
          </h2>
          <button
            type="button"
            aria-label="Editar nombre"
            className="text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <StatusBadge status={status} />
        </div>

        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Phone className="h-3.5 w-3.5 shrink-0" />
          <span className="font-mono tracking-tight">{phone}</span>
          <CopyBtn text={phone} />
        </div>

        {/* Chips */}
        <div className="flex flex-wrap gap-1.5 pt-1">
          {MOCK.chips.map(({ label, icon: Icon }) => (
            <span
              key={label}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            >
              <Icon className="h-3 w-3" />
              {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// QuickActions
// ─────────────────────────────────────────────────────────────────────────────

function QuickActions({ phone }: { phone: string }) {
  const actions = [
    {
      icon: MessageCircle,
      label: "WhatsApp",
      onClick: () => toast.info("Abriendo conversación de WhatsApp"),
    },
    {
      icon: Phone,
      label: "Llamar",
      onClick: () => toast.info(`Llamando a ${phone}…`),
    },
    {
      icon: StickyNote,
      label: "Nota",
      onClick: () => toast.info("Abre el panel de notas para escribir"),
    },
    {
      icon: CheckSquare,
      label: "Tarea",
      onClick: () => toast.info("Función de tareas próximamente"),
    },
    {
      icon: User,
      label: "Humano",
      onClick: () => toast.success("Conversación transferida a humano"),
    },
  ] as const;

  return (
    <div className="flex flex-wrap gap-2">
      {actions.map(({ icon: Icon, label, onClick }) => (
        <Button
          key={label}
          variant="outline"
          size="sm"
          className="gap-1.5 text-xs"
          onClick={onClick}
          aria-label={label}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </Button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LeadScoreCard
// ─────────────────────────────────────────────────────────────────────────────

function LeadScoreCard({ score }: { score: number }) {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <span>Score del lead</span>
        <Info className="h-3 w-3" />
      </div>
      <div className="mt-2 flex items-start justify-between gap-2">
        <div>
          <p className={cn("text-2xl font-bold", scoreLevelColor(MOCK.scoreLevel))}>
            {MOCK.scoreLevel}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground max-w-[140px]">
            {MOCK.scoreReasons}
          </p>
        </div>
        <CircularScore value={score} />
      </div>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NextActionCard
// ─────────────────────────────────────────────────────────────────────────────

function NextActionCard() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Send className="h-3.5 w-3.5 text-blue-500" />
        Siguiente acción
      </div>
      <p className="mt-2 text-sm text-foreground">{MOCK.nextAction}</p>
      <Button
        size="sm"
        className="mt-3 w-full"
        onClick={() => toast.success("Mensaje preparado")}
      >
        Enviar mensaje
      </Button>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LastMessageCard
// ─────────────────────────────────────────────────────────────────────────────

function LastMessageCard() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <MessageCircle className="h-3.5 w-3.5 text-emerald-500" />
        Último mensaje
      </div>
      <div className="mt-2 rounded-lg bg-muted px-3 py-2 text-sm">
        {MOCK.lastMessage.preview}
      </div>
      <p className="mt-1.5 flex items-center gap-1 text-xs text-muted-foreground">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 inline-block" />
        {MOCK.lastMessage.time}
      </p>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AdvisorCard
// ─────────────────────────────────────────────────────────────────────────────

function AdvisorCard() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <User className="h-3.5 w-3.5 text-muted-foreground" />
        Asignado a
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Avatar className="h-8 w-8">
          <AvatarFallback className="bg-primary/15 text-primary text-xs font-semibold">
            {MOCK.advisor.initials}
          </AvatarFallback>
        </Avatar>
        <span className="text-sm font-medium">{MOCK.advisor.name}</span>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="mt-3 w-full text-xs"
        onClick={() => toast.info("Función de reasignación próximamente")}
      >
        Cambiar asesor
      </Button>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SourceCard
// ─────────────────────────────────────────────────────────────────────────────

function SourceCard() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Globe className="h-3.5 w-3.5 text-muted-foreground" />
        Origen
      </div>
      <p className="mt-2 text-sm">{MOCK.source}</p>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ActivityTimeline
// ─────────────────────────────────────────────────────────────────────────────

function ActivityTimeline() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Activity className="h-3.5 w-3.5 text-muted-foreground" />
        Actividad
      </div>
      <ol className="mt-3 flex flex-col gap-2">
        {MOCK.activity.map((item, i) => (
          <li key={i} className="flex items-start gap-2">
            <div className="mt-1.5 flex flex-col items-center">
              <span
                className={cn(
                  "h-2 w-2 rounded-full shrink-0",
                  activityDotCn(item.type),
                )}
              />
              {i < MOCK.activity.length - 1 && (
                <span className="mt-1 h-full w-px bg-border" />
              )}
            </div>
            <div className="flex gap-2 text-xs min-w-0">
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {item.time}
              </span>
              <span className="leading-tight">{item.event}</span>
            </div>
          </li>
        ))}
      </ol>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AutomationCard
// ─────────────────────────────────────────────────────────────────────────────

function AutomationCard() {
  const { active, botName } = MOCK.automation;
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <BotMessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
        Automatización
      </div>
      <p className="mt-2 text-sm">
        <span className={active ? "text-emerald-500 font-medium" : "text-muted-foreground"}>
          {active ? "Activa" : "Pausada"}
        </span>
        {" · "}
        <span className="text-muted-foreground">{botName}</span>
      </p>
      <div className="mt-3 flex gap-2">
        <Button
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5 text-xs"
          onClick={() => toast.warning("Automatización pausada")}
        >
          <Pause className="h-3 w-3" />
          Pausar bot
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5 text-xs"
          onClick={() => toast.success("Conversación transferida")}
        >
          <UserCheck className="h-3 w-3" />
          Transferir a humano
        </Button>
      </div>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AlertsCard
// ─────────────────────────────────────────────────────────────────────────────

function AlertsCard() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
        Alertas
      </div>
      <ul className="mt-3 flex flex-col gap-1.5">
        {MOCK.alerts.map((alert, i) => (
          <li
            key={i}
            className="flex items-center gap-2 rounded-md bg-amber-500/8 px-2.5 py-1.5 text-xs"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500 shrink-0" />
            {alert}
          </li>
        ))}
      </ul>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FollowUpCard
// ─────────────────────────────────────────────────────────────────────────────

function FollowUpCard({ onSchedule }: { onSchedule: () => void }) {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
        Seguimiento
      </div>
      {MOCK.followUp ? (
        <>
          <p className="mt-2 text-sm font-medium">{MOCK.followUp.datetime}</p>
          <p className="text-xs text-muted-foreground">{MOCK.followUp.note}</p>
        </>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">Sin seguimiento programado</p>
      )}
      <Button
        variant="outline"
        size="sm"
        className="mt-3 gap-1.5 text-xs"
        onClick={onSchedule}
      >
        <Calendar className="h-3 w-3" />
        Programar
      </Button>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// RiskCard
// ─────────────────────────────────────────────────────────────────────────────

function RiskCard() {
  const { level, lastResponseAgo } = MOCK.abandonmentRisk;
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Zap className="h-3.5 w-3.5 text-amber-500" />
        Riesgo de abandono
      </div>
      <p className={cn("mt-2 text-xl font-bold", riskLevelColor(level))}>
        {level}
      </p>
      <p className="text-xs text-muted-foreground">
        Última respuesta hace {lastResponseAgo}
      </p>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BlockingCard
// ─────────────────────────────────────────────────────────────────────────────

function BlockingCard() {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Lock className="h-3.5 w-3.5 text-red-500" />
        Bloqueo actual
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        {MOCK.blockingReason ?? "Sin bloqueos activos"}
      </p>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DocumentsCard
// ─────────────────────────────────────────────────────────────────────────────

function DocumentsCard() {
  const completed = MOCK.documents.filter((d) => d.status === "completo").length;
  const total = MOCK.documents.length;

  return (
    <SCard className="p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold">
          <FileText className="h-3.5 w-3.5 text-muted-foreground" />
          Documentos
          <span className="ml-1 font-normal text-emerald-600">
            {completed}/{total} completos
          </span>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1 px-2 text-xs"
          onClick={() => toast.info("Función para agregar documentos próximamente")}
        >
          <Plus className="h-3 w-3" />
          Agregar
        </Button>
      </div>

      {/* Doc rows */}
      <ul className="mt-3 flex flex-col divide-y divide-border">
        {MOCK.documents.map(({ label, status }) => (
          <li
            key={label}
            className="flex items-center justify-between py-2 text-xs"
          >
            <div className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span>{label}:</span>
            </div>
            <span
              className={cn(
                "inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium",
                docStatusCn(status),
              )}
            >
              {status}
            </span>
          </li>
        ))}
      </ul>

      {/* Educational banner */}
      <div className="mt-3 flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/8 px-3 py-2.5 text-xs text-blue-600">
        <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
        <span>Agrega un checklist para guiar los siguientes pasos.</span>
      </div>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CustomFieldsCard
// ─────────────────────────────────────────────────────────────────────────────

function CustomFieldsCard({ onConfigure }: { onConfigure: () => void }) {
  return (
    <SCard className="p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold">
        <Sparkles className="h-3.5 w-3.5 text-muted-foreground" />
        Campos personalizados
      </div>

      <EmptyState
        icon={Plus}
        title="Sin campos definidos."
        hint="Configura campos personalizados para captar más información."
        action={{ label: "Configurar", onClick: onConfigure }}
      />

      {/* Suggested chips */}
      <div className="flex flex-wrap gap-1.5 pt-1">
        {MOCK.customFieldSuggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={onConfigure}
            className="rounded-md border border-border bg-muted px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {s}
          </button>
        ))}
      </div>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NoteItem
// ─────────────────────────────────────────────────────────────────────────────

function NoteItem({ note }: { note: CustomerNote }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: () =>
      notesApi.update(note.customer_id, note.id, { pinned: !note.pinned }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["customer-notes", note.customer_id] }),
  });

  return (
    <div
      className={cn(
        "rounded-lg border p-3 text-xs",
        note.pinned
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-border bg-card",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="leading-relaxed">{note.content}</p>
        <button
          type="button"
          aria-label={note.pinned ? "Desfijar" : "Fijar"}
          onClick={() => toggle.mutate()}
          className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
        >
          {note.pinned ? (
            <span className="text-amber-500">📌</span>
          ) : (
            <span>📌</span>
          )}
        </button>
      </div>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        {note.author_email ?? "Asesor"} ·{" "}
        {new Date(note.created_at).toLocaleString("es-MX", {
          dateStyle: "short",
          timeStyle: "short",
        })}
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NotesCard
// ─────────────────────────────────────────────────────────────────────────────

function NotesCard({
  customerId,
  onNewNote,
}: {
  customerId: string;
  onNewNote: () => void;
}) {
  const { data: notes = [] } = useQuery({
    queryKey: ["customer-notes", customerId],
    queryFn: () => notesApi.list(customerId),
  });

  const pinned = notes.filter((n) => n.pinned);
  const rest = notes.filter((n) => !n.pinned);

  return (
    <SCard className="p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <StickyNote className="h-4 w-4 text-muted-foreground" />
          Notas
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-7 gap-1.5 px-2 text-xs">
            <BrainCircuit className="h-3 w-3" />
            Resumen
          </Button>
          <Button size="sm" className="h-7 gap-1.5 px-2 text-xs" onClick={onNewNote}>
            <Plus className="h-3 w-3" />
            Nueva nota
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {/* AI Summary */}
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15">
              <BrainCircuit className="h-4 w-4 text-primary" />
            </div>
            <span className="text-xs font-semibold">Resumen IA</span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {MOCK.aiSummary}
          </p>
        </div>

        {/* Notes list or empty state */}
        <div>
          {notes.length === 0 ? (
            <EmptyState
              icon={StickyNote}
              title="Sin notas aún"
              hint="Agrega notas para mantener el contexto de la conversación."
              action={{ label: "Escribir nota", onClick: onNewNote }}
            />
          ) : (
            <div className="flex flex-col gap-2">
              {pinned.map((n) => (
                <NoteItem key={n.id} note={n} />
              ))}
              {rest.map((n) => (
                <NoteItem key={n.id} note={n} />
              ))}
            </div>
          )}
        </div>
      </div>
    </SCard>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Skeleton loader
// ─────────────────────────────────────────────────────────────────────────────

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6 animate-pulse">
      {/* Identity */}
      <div className="flex gap-4">
        <Skeleton className="h-14 w-14 rounded-full" />
        <div className="flex flex-col gap-2 pt-1">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-3.5 w-32" />
          <div className="flex gap-1.5 pt-1">
            {[...Array(4)].map((_, i) => (
              <Skeleton key={i} className="h-5 w-20 rounded-md" />
            ))}
          </div>
        </div>
      </div>
      {/* Quick actions */}
      <div className="flex gap-2">
        {[...Array(5)].map((_, i) => (
          <Skeleton key={i} className="h-8 w-20 rounded-md" />
        ))}
      </div>
      {/* Grid */}
      <div className="grid grid-cols-[1fr_288px] gap-4">
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-28 rounded-xl" />
            <Skeleton className="h-28 rounded-xl" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-24 rounded-xl" />
            <Skeleton className="h-24 rounded-xl" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-32 rounded-xl" />
            <Skeleton className="h-32 rounded-xl" />
          </div>
          <Skeleton className="h-48 rounded-xl" />
        </div>
        <div className="flex flex-col gap-4">
          <Skeleton className="h-28 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-28 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-16 rounded-xl" />
          <Skeleton className="h-48 rounded-xl" />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main export
// ─────────────────────────────────────────────────────────────────────────────

export function CustomerDetail({ customerId }: { customerId: string }) {
  const [followUpOpen, setFollowUpOpen] = useState(false);
  const [newNoteOpen, setNewNoteOpen] = useState(false);
  const [customFieldsOpen, setCustomFieldsOpen] = useState(false);

  const { data: customer, isLoading } = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => customersApi.getOne(customerId),
  });

  return (
    /* Escape the AppShell's p-6 to own our layout */
    <div className="-m-6 flex min-h-full flex-col bg-background">
      {/* ── Sub-header ───────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 flex h-13 items-center justify-between border-b border-border bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild aria-label="Volver">
            <Link to="/customers">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <h1 className="text-sm font-semibold">Contacto</h1>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Más opciones">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem onClick={() => toast.info("Función próximamente")}>
              <Pencil className="mr-2 h-3.5 w-3.5" />
              Editar contacto
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => toast.info("Función próximamente")}>
              <FileText className="mr-2 h-3.5 w-3.5" />
              Exportar datos
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-red-500 focus:text-red-500">
              Eliminar contacto
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      {/* ── Page content ─────────────────────────────────────────────────── */}
      <main className="flex flex-1 flex-col gap-5 p-6">
        {isLoading ? (
          <DetailSkeleton />
        ) : !customer ? (
          <EmptyState
            icon={User}
            title="Contacto no encontrado"
            hint="Este contacto no existe o fue eliminado."
          />
        ) : (
          <>
            {/* Identity + quick actions */}
            <div className="flex flex-col gap-4">
              <ContactIdentity
                name={customer.name}
                phone={customer.phone_e164}
                status={customer.conversations?.[0]?.status ?? "Activa"}
              />
              <QuickActions phone={customer.phone_e164} />
            </div>

            <Separator />

            {/* Operational grid */}
            <div className="grid gap-4 xl:grid-cols-[1fr_288px]">
              {/* ── Left column ─────────────────────────────────────────── */}
              <div className="flex flex-col gap-4">
                {/* Row 1: Next action + last message */}
                <div className="grid gap-4 sm:grid-cols-2">
                  <NextActionCard />
                  <LastMessageCard />
                </div>

                {/* Row 2: Source + activity */}
                <div className="grid gap-4 sm:grid-cols-2">
                  <SourceCard />
                  <ActivityTimeline />
                </div>

                {/* Row 3: Alerts + follow-up */}
                <div className="grid gap-4 sm:grid-cols-2">
                  <AlertsCard />
                  <FollowUpCard onSchedule={() => setFollowUpOpen(true)} />
                </div>

                {/* Documents */}
                <DocumentsCard />
              </div>

              {/* ── Right column ─────────────────────────────────────────── */}
              <div className="flex flex-col gap-4">
                <LeadScoreCard score={customer.score} />
                <AdvisorCard />
                <AutomationCard />
                <RiskCard />
                <BlockingCard />
                <CustomFieldsCard onConfigure={() => setCustomFieldsOpen(true)} />
              </div>
            </div>

            {/* Notes */}
            <NotesCard
              customerId={customerId}
              onNewNote={() => setNewNoteOpen(true)}
            />
          </>
        )}
      </main>

      {/* ── Dialogs ────────────────────────────────────────────────────── */}
      <FollowUpDialog open={followUpOpen} onClose={() => setFollowUpOpen(false)} />
      <NewNoteDialog
        open={newNoteOpen}
        onClose={() => setNewNoteOpen(false)}
        customerId={customerId}
      />
      <CustomFieldsDialog
        open={customFieldsOpen}
        onClose={() => setCustomFieldsOpen(false)}
      />
    </div>
  );
}

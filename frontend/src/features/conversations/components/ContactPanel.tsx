/**
 * ContactPanel - panel lateral de contacto en la vista de conversación.
 *
 * Diseño denso que replica el espíritu del mockup AtendIA v2:
 *  - Identidad del contacto (avatar, nombre, teléfono, badge de estado)
 *  - Score del lead + link a página completa
 *  - Acciones rápidas (WhatsApp, Llamar, Nota)
 *  - Sección de conversación (etapa, documentos checklist)
 *  - Campos personalizados con CRUD real
 *  - Notas con pin / editar / eliminar
 *
 * Toda la lógica de negocio (hooks, mutations) se preserva intacta.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BrainCircuit,
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  Image as ImageIcon,
  Info,
  Mail,
  MessageCircle,
  Pencil,
  Phone,
  Pin,
  PinOff,
  Plus,
  Save,
  Send,
  Sparkles,
  StickyNote,
  Target,
  Trash2,
  UserCheck,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { tenantsApi } from "@/features/config/api";
import {
  type ConversationAttachment,
  type ConversationDetail,
  conversationsApi,
} from "@/features/conversations/api";
import { AddCustomAttrDialog } from "@/features/conversations/components/AddCustomAttrDialog";
import { EditableDetailRow } from "@/features/conversations/components/EditableDetailRow";
import { useConversationAttachments } from "@/features/conversations/hooks/useConversations";
import {
  useCreateNote,
  useCustomerDetail,
  useCustomerNotes,
  useDeleteNote,
  useFieldDefinitions,
  useFieldValues,
  usePatchConversation,
  usePatchCustomer,
  usePutFieldValues,
  useUpdateNote,
} from "@/features/conversations/hooks/useContactPanel";
import { useCustomerAttrs } from "@/features/conversations/hooks/useCustomerAttrs";
import type {
  CustomerNote,
  CustomerDetail as CustomerRecord,
  FieldDefinition,
} from "@/features/customers/api";
import { cn } from "@/lib/utils";

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Props
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface Props {
  customerId: string | undefined;
  conversation?: ConversationDetail;
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Tiny helpers
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function getInitials(name: string | null, phone: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    return parts.length >= 2
      ? ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase()
      : (parts[0]?.slice(0, 2) ?? "").toUpperCase();
  }
  return phone.slice(-2);
}

function scoreLabel(score: number): { text: string; cn: string } {
  if (score >= 70) return { text: "Alto", cn: "text-emerald-500" };
  if (score >= 40) return { text: "Medio", cn: "text-amber-500" };
  return { text: "Bajo", cn: "text-red-500" };
}

function closeProbability(score: number): { label: string; helper: string; cn: string } {
  if (score >= 85) {
    return {
      label: "Excelente",
      helper: "Alta probabilidad de cierre",
      cn: "text-emerald-500",
    };
  }
  if (score >= 65) {
    return {
      label: "Media-Alta",
      helper: "Buen potencial si se atiende hoy",
      cn: "text-blue-500",
    };
  }
  if (score >= 40) {
    return {
      label: "Media",
      helper: "Requiere seguimiento claro",
      cn: "text-amber-500",
    };
  }
  return {
    label: "Baja",
    helper: "Necesita reactivacion",
    cn: "text-red-500",
  };
}

function rawValue(value: unknown): unknown {
  if (value && typeof value === "object" && !Array.isArray(value) && "value" in value) {
    return (value as { value?: unknown }).value;
  }
  return value;
}

function toDisplayValue(value: unknown): string | null {
  const raw = rawValue(value);
  if (raw === null || raw === undefined || raw === "") return null;
  if (typeof raw === "string") return raw;
  if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
  if (Array.isArray(raw)) {
    const parts = raw.map(toDisplayValue).filter(Boolean);
    return parts.length ? parts.join(", ") : null;
  }
  return null;
}

function getPathValue(source: Record<string, unknown> | null | undefined, path: string): unknown {
  if (!source) return undefined;
  let current: unknown = source;
  for (const part of path.split(".")) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

function pickValue(
  sources: Array<Record<string, unknown> | null | undefined>,
  keys: string[],
): string | null {
  for (const key of keys) {
    for (const source of sources) {
      const value = toDisplayValue(getPathValue(source, key));
      if (value) return value;
    }
  }
  return null;
}

function pickNumber(
  sources: Array<Record<string, unknown> | null | undefined>,
  keys: string[],
): number | null {
  for (const key of keys) {
    for (const source of sources) {
      const raw = rawValue(getPathValue(source, key));
      if (typeof raw === "number" && Number.isFinite(raw)) return raw;
      if (typeof raw === "string") {
        const parsed = Number(raw.replace(/[^\d.-]/g, ""));
        if (Number.isFinite(parsed)) return parsed;
      }
    }
  }
  return null;
}

function formatMoney(value: number | null): string | null {
  if (value === null) return null;
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency: "MXN",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatShortDateTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("es-MX", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatFileSize(bytes: number | null | undefined): string | null {
  if (!bytes || bytes <= 0) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatElapsed(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true, locale: es });
  } catch {
    return null;
  }
}

function normalizeIntent(intent: string | null | undefined): string {
  return (intent ?? "").trim().toUpperCase();
}

function getDetailSources(
  customer: CustomerRecord | undefined,
  conversation: ConversationDetail | undefined,
): Array<Record<string, unknown> | null | undefined> {
  return [conversation?.extracted_data, customer?.last_extracted_data, customer?.attrs];
}

function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "Sin etapa";
  return stage
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// CopyBtn
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  function handle() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    });
  }
  return (
    <button
      type="button"
      aria-label="Copiar"
      onClick={handle}
      className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Section label
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function SectionLabel({
  children,
  icon: Icon,
}: {
  children: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
      {Icon && <Icon className="h-3 w-3" />}
      {children}
    </div>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// ScoreBar â€” compact horizontal progress
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ScoreBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all duration-500", color)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// ContactIdentitySection
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ContactIdentitySection({ customerId }: { customerId: string }) {
  const customer = useCustomerDetail(customerId);
  const patch = usePatchCustomer(customerId);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  useEffect(() => {
    if (customer.data) {
      setName(customer.data.name ?? "");
      setEmail(customer.data.email ?? "");
    }
  }, [customer.data]);

  if (customer.isLoading) {
    return (
      <div className="flex gap-3 px-3 py-3">
        <Skeleton className="h-10 w-10 rounded-full shrink-0" />
        <div className="flex flex-col gap-1.5 flex-1">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-2 w-full" />
        </div>
      </div>
    );
  }
  if (!customer.data) return null;

  const c = customer.data;
  const abbr = getInitials(c.name, c.phone_e164);
  const sl = scoreLabel(c.score);

  const save = () => {
    patch.mutate(
      {
        name: name.trim() || undefined,
        email: email.trim() === "" ? null : email.trim(),
      },
      { onSuccess: () => setEditing(false) },
    );
  };

  return (
    <div className="px-3 py-3 space-y-3">
      {/* Avatar + name row */}
      <div className="flex items-start gap-2.5">
        {/* Avatar */}
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary">
          {abbr}
        </div>

        {/* Identity */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1">
            <span className="truncate text-sm font-semibold leading-tight">
              {c.name || "(sin nombre)"}
            </span>
            <button
              type="button"
              aria-label="Editar nombre"
              onClick={() => setEditing((v) => !v)}
              className="shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground"
            >
              <Pencil className="h-3 w-3" />
            </button>
          </div>

          <div className="flex items-center gap-1 mt-0.5">
            <Phone className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="text-xs font-mono text-muted-foreground truncate">{c.phone_e164}</span>
            <CopyBtn text={c.phone_e164} />
          </div>

          {c.email && (
            <div className="text-[11px] text-muted-foreground truncate mt-0.5">{c.email}</div>
          )}
        </div>

        {/* External link to full detail */}
        <Link
          to="/customers/$customerId"
          params={{ customerId }}
          aria-label="Ver perfil completo"
          className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {/* Edit form */}
      {editing && (
        <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-2.5">
          <div>
            <Label className="text-[11px]">Nombre</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-7 text-xs mt-0.5"
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
            />
          </div>
          <div>
            <Label className="text-[11px]">Email</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-7 text-xs mt-0.5"
              placeholder="cliente@ejemplo.com"
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
            />
          </div>
          <div className="flex gap-1">
            <Button
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={save}
              disabled={patch.isPending}
            >
              <Save className="mr-1 h-3 w-3" /> Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[11px]"
              onClick={() => {
                setName(c.name ?? "");
                setEmail(c.email ?? "");
                setEditing(false);
              }}
            >
              Cancelar
            </Button>
          </div>
        </div>
      )}

      {/* Score row */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">Score del lead</span>
          <span className={cn("text-xs font-bold", sl.cn)}>
            {sl.text} · {c.score}
          </span>
        </div>
        <ScoreBar value={c.score} />
      </div>

      {/* Stage chip */}
      {c.effective_stage && (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">Etapa:</span>
          <span className="inline-flex items-center rounded-md border border-border bg-muted px-1.5 py-0.5 text-[11px] font-medium">
            {c.effective_stage}
          </span>
        </div>
      )}
    </div>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// QuickActionsSection
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function QuickActionsSection({ phone }: { phone: string }) {
  // wa.me accepts the E.164 number with no leading '+' and opens the
  // operator's WhatsApp client (web or mobile) targeting that customer.
  // Strip the leading '+' if present so the deep-link works on both.
  const waPhone = phone.replace(/^\+/, "");
  return (
    <div className="flex gap-1.5 px-3 pb-3">
      <Button
        asChild
        variant="outline"
        size="sm"
        className="flex-1 h-7 gap-1 text-xs"
        aria-label="Abrir WhatsApp"
      >
        <a
          href={`https://wa.me/${waPhone}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <MessageCircle className="h-3.5 w-3.5" />
          Abrir WhatsApp
        </a>
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="flex-1 h-7 gap-1 text-xs"
        onClick={() => toast.info(`Llamando a ${phone}…`)}
        aria-label="Llamar"
      >
        <Phone className="h-3.5 w-3.5" />
        Llamar
      </Button>
    </div>
  );
}

function MiniSparkline({ score }: { score: number }) {
  const points = [42, 51, 49, 58, 62, 60, 72, Math.max(40, Math.min(96, score))];
  const width = 78;
  const height = 34;
  const step = width / (points.length - 1);
  const path = points
    .map((point, index) => {
      const x = index * step;
      const y = height - (point / 100) * height;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-8 w-20 overflow-visible"
      aria-hidden="true"
    >
      <path d={`${path} L ${width} ${height} L 0 ${height} Z`} className="fill-emerald-500/10" />
      <path d={path} className="fill-none stroke-emerald-500" strokeWidth="2" />
    </svg>
  );
}

function IntelligenceScoreSection({ customer }: { customer: CustomerRecord | undefined }) {
  if (!customer) {
    return (
      <div className="px-3 py-3">
        <Skeleton className="h-24 rounded-lg" />
      </div>
    );
  }

  const probability = closeProbability(customer.score);

  return (
    <div className="px-3 py-3">
      <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/8 p-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              <BrainCircuit className="h-3 w-3" />
              Lead score
            </div>
            <div className="mt-2 flex items-end gap-2">
              <span className="text-4xl font-bold leading-none text-emerald-500 tabular-nums">
                {customer.score}
              </span>
              <span className={cn("pb-1 text-xs font-semibold", probability.cn)}>
                {probability.label}
              </span>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              {probability.helper}
            </p>
          </div>
          <MiniSparkline score={customer.score} />
        </div>
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | null | undefined;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="min-w-0 rounded-md border border-border bg-muted/30 px-2 py-1.5">
      <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
        {Icon && <Icon className="h-3 w-3 shrink-0" />}
        <span>{label}</span>
      </div>
      <div className="mt-0.5 truncate text-[11px] font-medium">{value || "Sin dato"}</div>
    </div>
  );
}

const CREDIT_TYPE_OPTIONS = [
  { value: "Nómina Tarjeta", label: "Nómina Tarjeta" },
  { value: "Nómina Recibos", label: "Nómina Recibos" },
  { value: "Pensionados", label: "Pensionados" },
  { value: "Negocio SAT", label: "Negocio SAT" },
  { value: "Sin Comprobantes", label: "Sin Comprobantes" },
  { value: "Guardia de Seguridad", label: "Guardia de Seguridad" },
];

const PLAN_OPTIONS = [
  { value: "10%", label: "10%" },
  { value: "15%", label: "15%" },
  { value: "20%", label: "20%" },
  { value: "30%", label: "30%" },
];

// Keys that the canonical 5 attr-backed cards already render; the ad-hoc
// grid filters them out so users don't see them twice.
const CANONICAL_ATTR_KEYS = new Set([
  "estimated_value",
  "valor_estimado",
  "tipo_credito",
  "tipo_de_credito",
  "plan_credito",
  "plan_de_credito",
  "credito_plan",
  "modelo_interes",
  "producto",
  "modelo_moto",
  "city",
  "ciudad",
  "advisor_label",
]);
// Internal seed metadata â€” hide from ad-hoc grid.
const META_ATTR_KEYS = new Set(["mock_seed", "slug", "model_sku", "campaign"]);

const CANONICAL_FIELD_ALIASES: Record<string, string[]> = {
  estimated_value: ["estimated_value", "valor_estimado", "valor estimado"],
  tipo_credito: ["tipo_credito", "tipo_de_credito", "tipo credito", "tipo de credito"],
  plan_credito: [
    "plan_credito",
    "plan_de_credito",
    "credito_plan",
    "plan credito",
    "plan de credito",
    "credito plan",
  ],
  modelo_interes: ["modelo_interes", "modelo_moto", "modelo moto", "producto", "product"],
  city: ["city", "ciudad", "ubicacion", "ubicación"],
  advisor_label: ["advisor_label", "asesor", "advisor"],
};

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function normalizeFieldKey(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function aliasSetFor(canonicalKey: string): Set<string> {
  return new Set((CANONICAL_FIELD_ALIASES[canonicalKey] ?? [canonicalKey]).map(normalizeFieldKey));
}

function canonicalAttrKeysFor(canonicalKey: string): string[] {
  return CANONICAL_FIELD_ALIASES[canonicalKey]?.filter((key) => !key.includes(" ")) ?? [
    canonicalKey,
  ];
}

function isDocumentFieldKey(key: string): boolean {
  return /^DOCS_[A-Z0-9_]+$/.test(key);
}

function isDocumentDefinition(definition: FieldDefinition): boolean {
  return definition.field_type === "document" || isDocumentFieldKey(definition.key);
}

function valueFromAttrs(attrs: unknown, key: string, isDocument = isDocumentFieldKey(key)): string | null {
  if (!isPlainRecord(attrs)) return null;
  const raw = attrs[key];
  if (isDocument) {
    if (isPlainRecord(raw)) return toDisplayValue(raw.status);
    if (typeof raw === "boolean") return raw ? "ok" : "missing";
  }
  return toDisplayValue(raw);
}

function valueForDefinition(
  definition: FieldDefinition,
  configuredValues: Map<string, string | null>,
  attrs: unknown,
): string | null {
  if (isDocumentDefinition(definition)) {
    return (
      valueFromAttrs(attrs, definition.key, true) ?? configuredValues.get(definition.key) ?? null
    );
  }
  return configuredValues.get(definition.key) ?? valueFromAttrs(attrs, definition.key);
}

function ContactDetailGridSection({
  customerId,
  customer,
  conversation,
}: {
  customerId: string;
  customer: CustomerRecord | undefined;
  conversation: ConversationDetail | undefined;
}) {
  const patchCustomer = usePatchCustomer(customerId);
  const patchConversation = usePatchConversation(conversation?.id);
  const { patchAttr, deleteAttr } = useCustomerAttrs(customerId);
  const fieldDefinitions = useFieldDefinitions();
  const fieldValues = useFieldValues(customerId);
  const putFieldValues = usePutFieldValues(customerId);
  const pipeline = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });
  const [addOpen, setAddOpen] = useState(false);

  if (!customer) {
    return (
      <div className="px-3 py-3 space-y-2">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-16 rounded-lg" />
      </div>
    );
  }

  const sources = getDetailSources(customer, conversation);
  const configuredValueEntries = [
    ...(conversation?.customer_fields ?? []).map((field) => [field.key, field.value] as const),
    ...(fieldValues.data ?? []).map((field) => [field.key, field.value] as const),
  ];
  const configuredValues = new Map<string, string | null>(configuredValueEntries);
  const configuredValuesByNormalizedKey = new Map(
    configuredValueEntries.map(([key, value]) => [normalizeFieldKey(key), value]),
  );
  const fieldDefinitionsByNormalizedKey = new Map(
    (fieldDefinitions.data ?? []).map((definition) => [
      normalizeFieldKey(definition.key),
      definition,
    ]),
  );
  const configuredDefinitionFor = (canonicalKey: string): FieldDefinition | undefined =>
    [...aliasSetFor(canonicalKey)]
      .map((key) => fieldDefinitionsByNormalizedKey.get(key))
      .find((definition): definition is FieldDefinition => !!definition);
  const configuredFieldFor = (
    canonicalKey: string,
  ): { definition: FieldDefinition; value: string | null } | null => {
    const definition = configuredDefinitionFor(canonicalKey);
    if (!definition) return null;
    return { definition, value: configuredValues.get(definition.key) ?? null };
  };
  const displayValueFor = (canonicalKey: string, fallback: string | null): string | null => {
    const field = configuredFieldFor(canonicalKey);
    if (field?.value) return field.value;
    return fallback;
  };
  const displayLabelFor = (canonicalKey: string, fallback: string): string =>
    configuredDefinitionFor(canonicalKey)?.label ?? fallback;
  const saveConfiguredOrAttr = (
    canonicalKey: string,
    attrKey: string,
    value: string | number | null,
  ) => {
    const definition = configuredDefinitionFor(canonicalKey);
    if (definition) return putFieldValues.mutateAsync({ [definition.key]: value });
    return patchAttr.mutateAsync({ key: attrKey, value });
  };
  const deleteConfiguredOrAttr = (canonicalKey: string, attrKey: string) => {
    const definition = configuredDefinitionFor(canonicalKey);
    const duplicateAttrKeys = canonicalAttrKeysFor(canonicalKey).filter((key) => {
      const attrs = customer.attrs ?? {};
      return isPlainRecord(attrs) && Object.prototype.hasOwnProperty.call(attrs, key);
    });
    const tasks: Array<Promise<unknown>> = [];
    if (definition) tasks.push(putFieldValues.mutateAsync({ [definition.key]: null }));
    tasks.push(...duplicateAttrKeys.map((key) => deleteAttr.mutateAsync(key)));
    if (tasks.length === 0) return deleteAttr.mutateAsync(attrKey);
    return Promise.all(tasks);
  };
  const source =
    pickValue(sources, [
      "source",
      "fuente",
      "lead_source",
      "origen",
      "utm_source",
      "campaign.source",
    ]) ??
    customer.source ??
    null;
  const campaign = pickValue(sources, [
    "campaign",
    "campana",
    "campaign_name",
    "nombre_campana",
    "campaign.name",
  ]);
  const estimatedRaw = pickNumber(sources, [
    "estimated_value",
    "valor_estimado",
    "precio",
    "price",
  ]);
  const estimatedDisplay =
    formatMoney(estimatedRaw) ?? pickValue(sources, ["valor_estimado_label", "estimated_value_label"]);
  const creditType =
    pickValue(sources, ["tipo_credito", "tipo_de_credito", "credit_type"]);
  const creditPlan =
    pickValue(sources, ["plan_credito", "plan_de_credito", "credito_plan", "credit_plan"]);
  const product = pickValue(sources, [
    "modelo_interes",
    "modelo_moto",
    "producto",
    "product.name",
    "producto.modelo",
  ]);
  const city = pickValue(sources, ["ciudad", "city"]);
  const advisor =
    conversation?.assigned_agent_name ??
    conversation?.assigned_user_email ??
    pickValue(sources, ["advisor", "asesor", "advisor_label"]);

  const stages =
    (pipeline.data?.definition?.stages as Array<{ id: string; label?: string }> | undefined) ?? [];
  const stageOptions = stages.map((s) => ({
    value: s.id,
    label: s.label ?? s.id,
  }));

  const hiddenCustomKeys = new Set<string>([
    ...Object.values(CANONICAL_FIELD_ALIASES).flat().map(normalizeFieldKey),
    ...(fieldDefinitions.data ?? []).map((definition) => normalizeFieldKey(definition.key)),
  ]);
  const customAttrs = isPlainRecord(customer.attrs)
    ? Object.entries(customer.attrs).filter(
        ([k]) =>
          !CANONICAL_ATTR_KEYS.has(k) &&
          !META_ATTR_KEYS.has(k) &&
          !hiddenCustomKeys.has(normalizeFieldKey(k)),
      )
    : [];
  const additionalConfiguredFields = (fieldDefinitions.data ?? []).filter((definition) => {
    const normalized = normalizeFieldKey(definition.key);
    return !Object.keys(CANONICAL_FIELD_ALIASES).some((canonicalKey) =>
      aliasSetFor(canonicalKey).has(normalized),
    );
  });

  return (
    <div className="px-3 py-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <SectionLabel icon={Info}>Datos del cliente</SectionLabel>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={() => setAddOpen(true)}
        >
          <Plus className="mr-1 h-3 w-3" /> Agregar campo
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <EditableDetailRow
          label="Etapa"
          value={stageLabel(conversation?.current_stage ?? customer.effective_stage)}
          icon={Target}
          editable={!!conversation && stageOptions.length > 0}
          deletable={false}
          inputType="select"
          options={stageOptions}
          onSave={(v) => (v ? patchConversation.mutateAsync({ current_stage: v }) : undefined)}
        />
        <EditableDetailRow
          label="Fuente"
          value={campaign ? `${source ?? "WhatsApp"} · ${campaign}` : (source ?? "WhatsApp")}
          icon={Sparkles}
          editable
          deletable
          onSave={(v) => patchCustomer.mutateAsync({ source: v })}
          onDelete={() => patchCustomer.mutateAsync({ source: null })}
        />
        <EditableDetailRow
          label={displayLabelFor("advisor_label", "Asesor")}
          value={displayValueFor("advisor_label", advisor)}
          icon={UserCheck}
          editable
          deletable
          onSave={(v) => saveConfiguredOrAttr("advisor_label", "advisor_label", v)}
          onDelete={() => deleteConfiguredOrAttr("advisor_label", "advisor_label")}
        />
        <EditableDetailRow
          label={displayLabelFor("estimated_value", "Valor estimado")}
          value={displayValueFor("estimated_value", estimatedDisplay)}
          icon={Zap}
          editable
          deletable
          inputType="number"
          onSave={(v) =>
            saveConfiguredOrAttr("estimated_value", "estimated_value", v == null ? null : Number(v))
          }
          onDelete={() => deleteConfiguredOrAttr("estimated_value", "estimated_value")}
        />
        <EditableDetailRow
          label={displayLabelFor("tipo_credito", "Tipo de crédito")}
          value={displayValueFor("tipo_credito", creditType)}
          editable
          deletable
          inputType="select"
          options={CREDIT_TYPE_OPTIONS}
          onSave={(v) => saveConfiguredOrAttr("tipo_credito", "tipo_credito", v)}
          onDelete={() => deleteConfiguredOrAttr("tipo_credito", "tipo_credito")}
        />
        <EditableDetailRow
          label={displayLabelFor("plan_credito", "Plan de crédito")}
          value={displayValueFor("plan_credito", creditPlan)}
          editable
          deletable
          inputType="select"
          options={PLAN_OPTIONS}
          onSave={(v) => saveConfiguredOrAttr("plan_credito", "plan_credito", v)}
          onDelete={() => deleteConfiguredOrAttr("plan_credito", "plan_credito")}
        />
        <EditableDetailRow
          label={displayLabelFor("modelo_interes", "Producto")}
          value={displayValueFor("modelo_interes", product)}
          editable
          deletable
          onSave={(v) => saveConfiguredOrAttr("modelo_interes", "modelo_interes", v)}
          onDelete={() => deleteConfiguredOrAttr("modelo_interes", "modelo_interes")}
        />
        <EditableDetailRow
          label={displayLabelFor("city", "Ubicación")}
          value={displayValueFor("city", city)}
          editable
          deletable
          onSave={(v) => saveConfiguredOrAttr("city", "city", v)}
          onDelete={() => deleteConfiguredOrAttr("city", "city")}
        />
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <EditableDetailRow
          label="Teléfono"
          value={customer.phone_e164}
          icon={Phone}
          editable={false}
          deletable={false}
          onSave={() => {}}
        />
        <EditableDetailRow
          label="Email"
          value={customer.email}
          icon={Mail}
          editable
          deletable
          inputType="email"
          validate={(v) => (v === "" || /^.+@.+\..+$/.test(v) ? null : "Email inválido")}
          onSave={(v) => patchCustomer.mutateAsync({ email: v })}
          onDelete={() => patchCustomer.mutateAsync({ email: null })}
        />
      </div>

      {(additionalConfiguredFields.length > 0 || customAttrs.length > 0) && (
        <div className="grid grid-cols-2 gap-1.5 pt-1">
          {additionalConfiguredFields.map((definition) => {
            const value = valueForDefinition(definition, configuredValues, customer.attrs) ?? null;
            const inputType =
              definition.field_type === "number"
                ? "number"
                : definition.field_type === "select" || isDocumentDefinition(definition)
                  ? "select"
                  : "text";
            const options =
              isDocumentDefinition(definition)
                ? [
                    { value: "missing", label: "Pendiente" },
                    { value: "ok", label: "Recibido" },
                    { value: "rejected", label: "Rechazado" },
                  ]
                : definition.field_type === "select"
                ? ((definition.field_options as { choices?: string[] } | null)?.choices ?? []).map(
                    (choice) => ({ value: choice, label: choice }),
                  )
                : undefined;
            return (
              <EditableDetailRow
                key={definition.id}
                label={definition.label}
                value={value}
                editable
                deletable
                inputType={inputType}
                options={options}
                onSave={(next) =>
                  isDocumentDefinition(definition)
                    ? patchAttr.mutateAsync({
                        key: definition.key,
                        value: next ? { status: next } : { status: "missing" },
                      })
                    : putFieldValues.mutateAsync({ [definition.key]: next })
                }
                onDelete={() =>
                  isDocumentDefinition(definition)
                    ? deleteAttr.mutateAsync(definition.key)
                    : putFieldValues.mutateAsync({ [definition.key]: null })
                }
              />
            );
          })}
          {customAttrs.map(([k, v]) => (
            <EditableDetailRow
              key={k}
              label={k.replace(/_/g, " ")}
              value={
                v == null
                  ? null
                  : typeof v === "string" || typeof v === "number" || typeof v === "boolean"
                    ? String(v)
                    : JSON.stringify(v)
              }
              editable
              deletable
              onSave={(next) => patchAttr.mutateAsync({ key: k, value: next })}
              onDelete={() => deleteAttr.mutateAsync(k)}
            />
          ))}
        </div>
      )}

      <div className="text-[10px] text-muted-foreground">
        Última actividad: {formatElapsed(customer.last_activity_at) ?? "sin registro"}
      </div>

      <AddCustomAttrDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSubmit={(payload) =>
          patchAttr.mutate({
            key: payload.key,
            value:
              payload.field_type === "number"
                ? Number(payload.value)
                : payload.field_type === "boolean"
                  ? payload.value === "true" || payload.value === "1"
                  : payload.value,
          })
        }
      />
    </div>
  );
}

function missingDocs(conversation: ConversationDetail | undefined) {
  return conversation?.required_docs.filter((doc) => !doc.present) ?? [];
}

function completedDocs(conversation: ConversationDetail | undefined) {
  return conversation?.required_docs.filter((doc) => doc.present) ?? [];
}

function MissingDocumentsSection({
  customerId,
  conversation,
}: {
  customerId: string;
  conversation: ConversationDetail | undefined;
}) {
  const missing = missingDocs(conversation);
  const completed = completedDocs(conversation);
  const total = conversation?.required_docs.length ?? 0;

  return (
    <div className="px-3 py-3">
      <div
        className={cn(
          "rounded-lg border p-3",
          missing.length > 0
            ? "border-red-500/25 bg-red-500/8"
            : "border-emerald-500/20 bg-emerald-500/8",
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            <FileText
              className={cn(
                "h-3.5 w-3.5",
                missing.length > 0 ? "text-red-500" : "text-emerald-500",
              )}
            />
            Documentos
          </div>
          {total > 0 && (
            <span className="rounded-full border border-border bg-background/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {completed.length}/{total}
            </span>
          )}
        </div>

        {total === 0 ? (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Sin checklist asignado para este contacto.
          </p>
        ) : missing.length === 0 ? (
          <p className="mt-2 text-[11px] text-emerald-600">Documentacion completa para avanzar.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {missing.slice(0, 3).map((doc) => (
              <li key={doc.field_name} className="flex items-center gap-1.5 text-[11px]">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                <span className="min-w-0 truncate">{doc.label}</span>
              </li>
            ))}
          </ul>
        )}

        <Link
          to="/customers/$customerId"
          params={{ customerId }}
          className="mt-2 inline-flex text-[11px] font-medium text-primary hover:underline"
        >
          Ver detalle del contacto
        </Link>
      </div>
    </div>
  );
}

function attachmentLabel(item: ConversationAttachment): string {
  return item.original_filename || item.caption || item.mime_type || "Archivo";
}

function MultimediaSection({ conversationId }: { conversationId: string | undefined }) {
  const attachments = useConversationAttachments(conversationId ?? "");
  const items = attachments.data ?? [];

  return (
    <div className="px-3 py-3">
      <div className="rounded-lg border border-border bg-background/60 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            <ImageIcon className="h-3.5 w-3.5 text-blue-500" />
            Multimedia
          </div>
          {items.length > 0 && (
            <span className="rounded-full border border-border bg-muted/50 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {items.length}
            </span>
          )}
        </div>

        {attachments.isLoading ? (
          <div className="mt-3 space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : items.length === 0 ? (
          <p className="mt-2 text-[11px] text-muted-foreground">Sin archivos recibidos.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {items.slice(0, 6).map((item) => {
              const isImage = item.mime_type?.startsWith("image/");
              const size = formatFileSize(item.file_size);
              const when = formatShortDateTime(item.sent_at || item.created_at);

              return (
                <a
                  key={item.id}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex min-w-0 items-center gap-2 rounded-md border border-border/70 bg-muted/25 p-2 transition-colors hover:bg-muted/50"
                >
                  {isImage ? (
                    <img
                      src={item.url}
                      alt={attachmentLabel(item)}
                      className="h-9 w-9 shrink-0 rounded object-cover"
                    />
                  ) : (
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-background text-muted-foreground">
                      <FileText className="h-4 w-4" />
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[11px] font-medium">
                      {attachmentLabel(item)}
                    </span>
                    <span className="block truncate text-[10px] text-muted-foreground">
                      {[item.type, size, when].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                </a>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function suggestedNextAction(
  customer: CustomerRecord | undefined,
  conversation: ConversationDetail | undefined,
): string {
  const missing = missingDocs(conversation);
  const intent = normalizeIntent(conversation?.last_intent);
  const stage = normalizeIntent(conversation?.current_stage);

  if (conversation?.has_pending_handoff) {
    return "Asignar a un humano y revisar el motivo del handoff antes de responder.";
  }
  if (missing.length > 0) {
    return `Solicitar ${missing[0]?.label ?? "documentos faltantes"} para continuar la evaluacion.`;
  }
  if (
    customer &&
    customer.score >= 80 &&
    !stage.includes("CITA") &&
    !stage.includes("APPOINTMENT")
  ) {
    return "Agendar prueba de manejo y confirmar disponibilidad del asesor.";
  }
  if (intent.includes("ASK_PRICE") || intent.includes("PRICE")) {
    return "Enviar cotizacion personalizada y resolver dudas de financiamiento.";
  }
  if (conversation?.bot_paused) {
    return "Dar seguimiento humano y definir si se reactiva la IA.";
  }
  return "Enviar seguimiento breve con la siguiente pregunta comercial.";
}

function NextBestActionSection({
  customer,
  conversation,
}: {
  customer: CustomerRecord | undefined;
  conversation: ConversationDetail | undefined;
}) {
  const action = suggestedNextAction(customer, conversation);

  return (
    <div className="px-3 py-3">
      <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/8 p-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold">
          <Sparkles className="h-3.5 w-3.5 text-emerald-500" />
          Next Best Action
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{action}</p>
        <Button
          size="sm"
          className="mt-3 h-7 w-full gap-1.5 text-xs"
          onClick={() => toast.success("Acción preparada", { description: action })}
        >
          <Send className="h-3 w-3" />
          Ejecutar acción
        </Button>
      </div>
    </div>
  );
}

function buildRisks(
  customer: CustomerRecord | undefined,
  conversation: ConversationDetail | undefined,
): string[] {
  const risks: string[] = [];
  const lastActivityAt = conversation?.last_activity_at ?? customer?.last_activity_at;
  const lastActivityMs = lastActivityAt ? Date.now() - new Date(lastActivityAt).getTime() : 0;

  if (lastActivityMs > 2 * 60 * 60 * 1000) {
    risks.push("Tiempo sin respuesta mayor a 2 horas.");
  }
  if (conversation?.assigned_user_id === null && conversation?.assigned_agent_id === null) {
    risks.push("Conversación sin asesor asignado.");
  }
  if (conversation?.has_pending_handoff) {
    risks.push("Handoff pendiente de revisión.");
  }
  if (conversation?.bot_paused) {
    risks.push("IA pausada; el seguimiento depende del operador.");
  }
  if (missingDocs(conversation).length > 0) {
    risks.push("Documentos faltantes bloquean el avance.");
  }
  if (customer && customer.score < 45) {
    risks.push("Lead score bajo; requiere reactivacion.");
  }

  return risks.slice(0, 4);
}

function RisksDetectedSection({
  customer,
  conversation,
}: {
  customer: CustomerRecord | undefined;
  conversation: ConversationDetail | undefined;
}) {
  const risks = buildRisks(customer, conversation);

  return (
    <div className="px-3 py-3">
      <div
        className={cn(
          "rounded-lg border p-3",
          risks.length > 0
            ? "border-amber-500/25 bg-amber-500/8"
            : "border-emerald-500/20 bg-emerald-500/8",
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            <AlertTriangle
              className={cn(
                "h-3.5 w-3.5",
                risks.length > 0 ? "text-amber-500" : "text-emerald-500",
              )}
            />
            Riesgos detectados
          </div>
          {risks.length > 0 && (
            <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-600">
              {risks.length}
            </span>
          )}
        </div>
        {risks.length === 0 ? (
          <p className="mt-2 text-[11px] text-emerald-600">Sin riesgos operativos relevantes.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {risks.map((risk) => (
              <li key={risk} className="flex items-start gap-1.5 text-[11px] leading-relaxed">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                <span>{risk}</span>
              </li>
            ))}
          </ul>
        )}
        <button
          type="button"
          className="mt-2 text-[11px] font-medium text-primary hover:underline"
          onClick={() =>
            toast.info("Recomendaciones listas", {
              description: suggestedNextAction(customer, conversation),
            })
          }
        >
          Ver recomendaciones
        </button>
      </div>
    </div>
  );
}

function EventTimelineSection({ conversation }: { conversation: ConversationDetail | undefined }) {
  const entries = [
    {
      label: "Conversación iniciada",
      time: formatShortDateTime(conversation?.created_at),
      tone: "bg-blue-500",
    },
    {
      label: `Etapa actual: ${stageLabel(conversation?.current_stage)}`,
      time: formatShortDateTime(conversation?.last_activity_at),
      tone: "bg-purple-500",
    },
    ...completedDocs(conversation)
      .slice(0, 2)
      .map((doc) => ({
        label: `${doc.label} recibido`,
        time: formatShortDateTime(conversation?.last_activity_at),
        tone: "bg-emerald-500",
      })),
    {
      label: conversation?.last_intent
        ? `${normalizeIntent(conversation.last_intent)} detectado`
        : "Intención pendiente",
      time: formatShortDateTime(conversation?.last_inbound_at ?? conversation?.last_activity_at),
      tone: "bg-amber-500",
    },
  ].filter((entry) => entry.time || entry.label);

  return (
    <div className="px-3 py-3 space-y-2.5">
      <SectionLabel icon={CalendarClock}>Historial de eventos</SectionLabel>
      <ol className="space-y-2">
        {entries.slice(0, 5).map((entry, index) => (
          <li key={`${entry.label}-${entry.time ?? "pending"}`} className="flex gap-2 text-[11px]">
            <div className="flex flex-col items-center">
              <span className={cn("mt-1 h-2 w-2 rounded-full", entry.tone)} />
              {index < Math.min(entries.length, 5) - 1 && (
                <span className="mt-1 h-full min-h-4 w-px bg-border" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{entry.label}</div>
              <div className="text-[10px] text-muted-foreground">{entry.time ?? "Sin fecha"}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// ConversationSummarySection
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ConversationSummarySection({ conversation }: { conversation: ConversationDetail }) {
  const qc = useQueryClient();
  const pipeline = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
  });
  const patch = useMutation({
    mutationFn: (stage: string) =>
      conversationsApi.patchConversation(conversation.id, {
        current_stage: stage,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["conversation", conversation.id] });
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const stages =
    (pipeline.data?.definition?.stages as Array<{ id: string; label?: string }> | undefined) ?? [];

  const completedDocs = conversation.required_docs.filter((d) => d.present).length;
  const totalDocs = conversation.required_docs.length;

  return (
    <div className="px-3 py-3 space-y-3">
      <SectionLabel icon={Activity}>Conversación</SectionLabel>

      {/* Stage selector */}
      <div>
        <Label className="text-[11px] text-muted-foreground">Etapa</Label>
        <Select value={conversation.current_stage} onValueChange={(stage) => patch.mutate(stage)}>
          <SelectTrigger className="mt-0.5 h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {stages.map((stage) => (
              <SelectItem key={stage.id} value={stage.id} className="text-xs">
                {stage.label ?? stage.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Documents checklist */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">Documentos</span>
          {totalDocs > 0 && (
            <span
              className={cn(
                "text-[11px] font-medium",
                completedDocs === totalDocs ? "text-emerald-500" : "text-amber-500",
              )}
            >
              {completedDocs}/{totalDocs}
            </span>
          )}
        </div>
        {conversation.required_docs.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">Sin checklist.</p>
        ) : (
          <ul className="space-y-1">
            {conversation.required_docs.map((doc) => (
              <li
                key={doc.field_name}
                className="flex items-center justify-between rounded-md border border-border bg-card px-2 py-1"
              >
                <span className="text-[11px] truncate">{doc.label}</span>
                <span
                  className={cn(
                    "ml-2 shrink-0 inline-flex items-center rounded border px-1 py-0.5 text-[10px] font-medium",
                    doc.present
                      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-600"
                      : "border-amber-500/20 bg-amber-500/10 text-amber-600",
                  )}
                >
                  {doc.present ? "Listo" : "Pendiente"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// NotesSection â€” full logic preserved, improved visuals
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function NotesSection({
  customerId,
  conversationId,
}: {
  customerId: string;
  conversationId?: string;
}) {
  const notes = useCustomerNotes(customerId);
  const createNote = useCreateNote(customerId);
  const qc = useQueryClient();
  const forceSummary = useMutation({
    mutationFn: () => conversationsApi.forceSummary(conversationId!),
    onSuccess: () => {
      setTimeout(() => {
        void qc.invalidateQueries({ queryKey: ["customer-notes", customerId] });
      }, 1200);
    },
  });
  const [composing, setComposing] = useState(false);
  const [newContent, setNewContent] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (composing) textareaRef.current?.focus();
  }, [composing]);

  const submit = () => {
    const text = newContent.trim();
    if (!text) return;
    createNote.mutate(
      { content: text },
      {
        onSuccess: () => {
          setNewContent("");
          setComposing(false);
        },
      },
    );
  };

  return (
    <div className="px-3 py-3 space-y-2.5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <SectionLabel icon={StickyNote}>Notas</SectionLabel>
        <div className="flex gap-1">
          {conversationId && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[11px] text-muted-foreground"
              onClick={() => forceSummary.mutate()}
              disabled={forceSummary.isPending}
              aria-label="Generar resumen IA"
            >
              {forceSummary.isPending ? "Generando…" : "Resumen"}
            </Button>
          )}
          {!composing && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setComposing(true)}
              aria-label="Nueva nota"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Compose area */}
      {composing && (
        <div className="space-y-1.5 rounded-lg border border-border bg-muted/40 p-2.5">
          <Textarea
            ref={textareaRef}
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Escribe una nota…"
            rows={3}
            className="text-xs resize-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
              if (e.key === "Escape") {
                setComposing(false);
                setNewContent("");
              }
            }}
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">Ctrl+Enter para guardar</span>
            <div className="flex gap-1">
              <Button
                size="sm"
                className="h-6 px-2 text-[11px]"
                onClick={submit}
                disabled={!newContent.trim() || createNote.isPending}
              >
                Guardar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 w-6 p-0"
                onClick={() => {
                  setComposing(false);
                  setNewContent("");
                }}
                aria-label="Cancelar"
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {notes.isLoading && <Skeleton className="h-14 rounded-lg" />}

      {/* Empty state */}
      {!notes.isLoading && notes.data?.length === 0 && !composing && (
        <button
          type="button"
          onClick={() => setComposing(true)}
          className="w-full rounded-lg border border-dashed border-border py-4 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          Sin notas aún · <span className="text-primary">Escribir nota</span>
        </button>
      )}

      {/* Note cards */}
      {notes.data?.map((note) => (
        <NoteCard key={note.id} note={note} customerId={customerId} />
      ))}
    </div>
  );
}

function NoteCard({ note, customerId }: { note: CustomerNote; customerId: string }) {
  const updateNote = useUpdateNote(customerId);
  const deleteNote = useDeleteNote(customerId);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(note.content);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const wasEdited = note.updated_at !== note.created_at;
  const relativeTime = formatDistanceToNow(new Date(note.created_at), {
    addSuffix: true,
    locale: es,
  });

  const saveEdit = () => {
    const text = editContent.trim();
    if (!text) return;
    updateNote.mutate({ noteId: note.id, content: text }, { onSuccess: () => setEditing(false) });
  };

  const togglePin = () => {
    updateNote.mutate({ noteId: note.id, pinned: !note.pinned });
  };

  const doDelete = () => {
    deleteNote.mutate(note.id, { onSuccess: () => setConfirmDelete(false) });
  };

  return (
    <div
      className={cn(
        "rounded-lg border p-2.5 text-xs space-y-1.5 transition-colors",
        note.pinned ? "border-amber-500/30 bg-amber-500/5" : "border-border bg-card",
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-1">
        <div className="flex flex-wrap items-center gap-x-1 min-w-0">
          <span className="font-medium truncate max-w-[100px]">
            {note.author_email?.split("@")[0] ?? "Sistema"}
          </span>
          <span className="text-[10px] text-muted-foreground shrink-0">· {relativeTime}</span>
          {wasEdited && (
            <span className="text-[10px] text-muted-foreground shrink-0">· editada</span>
          )}
          {note.pinned && (
            <span className="inline-flex items-center gap-0.5 rounded border border-amber-500/20 bg-amber-500/10 px-1 py-0 text-[10px] text-amber-600">
              <Pin className="h-2 w-2" /> Fijada
            </span>
          )}
        </div>

        {/* Actions */}
        <div className="flex shrink-0 gap-0.5">
          <button
            type="button"
            aria-label={note.pinned ? "Desfijar" : "Fijar"}
            onClick={togglePin}
            className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
          >
            {note.pinned ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}
          </button>
          <button
            type="button"
            aria-label="Editar nota"
            onClick={() => {
              setEditContent(note.content);
              setEditing(true);
            }}
            className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
          >
            <Pencil className="h-3 w-3" />
          </button>
          <button
            type="button"
            aria-label="Eliminar nota"
            onClick={() => setConfirmDelete(true)}
            className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-red-500"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Body */}
      {editing ? (
        <div className="space-y-1.5">
          <Textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            rows={3}
            className="text-xs resize-none"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                saveEdit();
              }
              if (e.key === "Escape") setEditing(false);
            }}
          />
          <div className="flex gap-1">
            <Button
              size="sm"
              className="h-6 px-2 text-[11px]"
              onClick={saveEdit}
              disabled={updateNote.isPending}
            >
              Guardar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[11px]"
              onClick={() => setEditing(false)}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap leading-relaxed">{note.content}</p>
      )}

      {/* Confirm delete */}
      {confirmDelete && (
        <div className="flex items-center gap-1.5 rounded-md border border-destructive/20 bg-destructive/8 px-2 py-1.5">
          <span className="flex-1 text-[11px]">¿Eliminar esta nota?</span>
          <Button
            size="sm"
            variant="destructive"
            className="h-6 px-2 text-[11px]"
            onClick={doDelete}
            disabled={deleteNote.isPending}
          >
            Eliminar
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-[11px]"
            onClick={() => setConfirmDelete(false)}
          >
            No
          </Button>
        </div>
      )}
    </div>
  );
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Main export
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const COLLAPSE_KEY = "atendia.contactPanel.collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function ContactPanel({ customerId, conversation }: Props) {
  // Collapse preference persists across remounts: the panel is unmounted
  // whenever the operator opens the DebugPanel, so a plain useState would
  // reset the drawer every time they inspect a trace.
  const [collapsed, setCollapsedState] = useState<boolean>(readCollapsed);
  const setCollapsed = (v: boolean) => {
    setCollapsedState(v);
    try {
      window.localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0");
    } catch {
      /* storage disabled / over quota â€” non-fatal */
    }
  };
  const customer = useCustomerDetail(customerId ?? "");

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        aria-label="Expandir inteligencia del cliente"
        className="flex h-full w-3 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border bg-muted/40 transition-colors hover:bg-muted"
      >
        <ChevronLeft className="h-3 w-3 text-muted-foreground" />
      </button>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-80 shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground">
      {/* â”€â”€ Panel header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-3">
        <div className="min-w-0">
          <span className="block truncate text-xs font-semibold">Inteligencia del cliente</span>
          <span className="block truncate text-[10px] text-muted-foreground">
            contacto, riesgo y siguiente acción
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          {customerId && (
            <Link
              to="/customers/$customerId"
              params={{ customerId }}
              aria-label="Abrir perfil completo"
              className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <ExternalLink className="h-3 w-3" />
            </Link>
          )}
          <button
            type="button"
            aria-label="Colapsar panel"
            onClick={() => setCollapsed(true)}
            className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* â”€â”€ Scrollable body â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <ScrollArea className="min-h-0 flex-1 overflow-hidden">
        <div>
          {customerId ? (
            <>
              {/* Contact identity */}
              <ContactIdentitySection customerId={customerId} />

              {/* Quick actions */}
              {customer.data && <QuickActionsSection phone={customer.data.phone_e164} />}

              <Separator />
              <IntelligenceScoreSection customer={customer.data} />

              <Separator />
              <ContactDetailGridSection
                customerId={customerId}
                customer={customer.data}
                conversation={conversation}
              />

              <Separator />
              <MissingDocumentsSection customerId={customerId} conversation={conversation} />

              <Separator />
              <MultimediaSection conversationId={conversation?.id} />

              <Separator />
              <NextBestActionSection customer={customer.data} conversation={conversation} />

              <Separator />
              <RisksDetectedSection customer={customer.data} conversation={conversation} />

              <Separator />
              <EventTimelineSection conversation={conversation} />

              {/* Conversation controls */}
              {conversation && (
                <>
                  <Separator />
                  <ConversationSummarySection conversation={conversation} />
                </>
              )}

              {/* Notes */}
              <Separator />
              <NotesSection customerId={customerId} conversationId={conversation?.id} />
            </>
          ) : (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">
              Selecciona una conversación.
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

/**
 * ContactPanel — panel lateral de contacto en la vista de conversación.
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
import { formatDistanceToNow } from "date-fns";
import { es } from "date-fns/locale";
import {
  Activity,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  MessageCircle,
  MoreHorizontal,
  Pencil,
  Phone,
  Pin,
  PinOff,
  Plus,
  Save,
  StickyNote,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { conversationsApi, type ConversationDetail } from "@/features/conversations/api";
import type { CustomerNote, FieldDefinition } from "@/features/customers/api";
import {
  useCreateNote,
  useCustomerDetail,
  useCustomerNotes,
  useDeleteNote,
  useFieldDefinitions,
  useFieldValues,
  usePatchCustomer,
  usePutFieldValues,
  useUpdateNote,
} from "@/features/conversations/hooks/useContactPanel";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────────

interface Props {
  customerId: string | undefined;
  conversation?: ConversationDetail;
}

// ─────────────────────────────────────────────────────────────────────────────
// Tiny helpers
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
// CopyBtn
// ─────────────────────────────────────────────────────────────────────────────

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
      {copied ? (
        <Check className="h-3 w-3 text-emerald-500" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Section label
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
// ScoreBar — compact horizontal progress
// ─────────────────────────────────────────────────────────────────────────────

function ScoreBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const color =
    pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all duration-500", color)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ContactIdentitySection
// ─────────────────────────────────────────────────────────────────────────────

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
            <span className="text-xs font-mono text-muted-foreground truncate">
              {c.phone_e164}
            </span>
            <CopyBtn text={c.phone_e164} />
          </div>

          {c.email && (
            <div className="text-[11px] text-muted-foreground truncate mt-0.5">
              {c.email}
            </div>
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

// ─────────────────────────────────────────────────────────────────────────────
// QuickActionsSection
// ─────────────────────────────────────────────────────────────────────────────

function QuickActionsSection({ phone }: { phone: string }) {
  return (
    <div className="flex gap-1.5 px-3 pb-3">
      <Button
        variant="outline"
        size="sm"
        className="flex-1 h-7 gap-1 text-xs"
        onClick={() => toast.info("Abriendo conversación de WhatsApp")}
        aria-label="WhatsApp"
      >
        <MessageCircle className="h-3.5 w-3.5 text-emerald-500" />
        WhatsApp
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

// ─────────────────────────────────────────────────────────────────────────────
// ConversationSummarySection
// ─────────────────────────────────────────────────────────────────────────────

function ConversationSummarySection({
  conversation,
}: {
  conversation: ConversationDetail;
}) {
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
    (
      pipeline.data?.definition?.stages as
        | Array<{ id: string; label?: string }>
        | undefined
    ) ?? [];

  const completedDocs = conversation.required_docs.filter((d) => d.present).length;
  const totalDocs = conversation.required_docs.length;

  return (
    <div className="px-3 py-3 space-y-3">
      <SectionLabel icon={Activity}>Conversación</SectionLabel>

      {/* Stage selector */}
      <div>
        <Label className="text-[11px] text-muted-foreground">Etapa</Label>
        <Select
          value={conversation.current_stage}
          onValueChange={(stage) => patch.mutate(stage)}
        >
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
                completedDocs === totalDocs
                  ? "text-emerald-500"
                  : "text-amber-500",
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

// ─────────────────────────────────────────────────────────────────────────────
// CustomFieldsSection — full CRUD preserved
// ─────────────────────────────────────────────────────────────────────────────

function CustomFieldsSection({ customerId }: { customerId: string }) {
  const defs = useFieldDefinitions();
  const vals = useFieldValues(customerId);
  const putValues = usePutFieldValues(customerId);
  const [draft, setDraft] = useState<Record<string, string | null>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (vals.data) {
      const map: Record<string, string | null> = {};
      for (const v of vals.data) map[v.key] = v.value;
      setDraft(map);
      setDirty(false);
    }
  }, [vals.data]);

  if (defs.isLoading || vals.isLoading) {
    return (
      <div className="px-3 py-3 space-y-2">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-7 w-full" />
      </div>
    );
  }

  if (!defs.data?.length) {
    return (
      <div className="px-3 py-3 space-y-1">
        <SectionLabel>Campos personalizados</SectionLabel>
        <p className="text-[11px] text-muted-foreground">Sin campos definidos.</p>
      </div>
    );
  }

  const update = (key: string, value: string | null) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  const save = () => {
    putValues.mutate(draft, { onSuccess: () => setDirty(false) });
  };

  return (
    <div className="px-3 py-3 space-y-2.5">
      <SectionLabel>Campos personalizados</SectionLabel>
      <div className="space-y-2">
        {defs.data.map((d) => (
          <FieldInput
            key={d.id}
            definition={d}
            value={draft[d.key] ?? ""}
            onChange={update}
          />
        ))}
      </div>
      {dirty && (
        <Button
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={save}
          disabled={putValues.isPending}
        >
          <Save className="mr-1 h-3 w-3" />
          {putValues.isPending ? "Guardando…" : "Guardar campos"}
        </Button>
      )}
    </div>
  );
}

function FieldInput({
  definition,
  value,
  onChange,
}: {
  definition: FieldDefinition;
  value: string;
  onChange: (key: string, value: string | null) => void;
}) {
  const { key, label, field_type, field_options } = definition;
  const choices = (field_options as { choices?: string[] } | null)?.choices ?? [];

  if (field_type === "select") {
    return (
      <div>
        <Label className="text-[11px]">{label}</Label>
        <Select value={value || ""} onValueChange={(v) => onChange(key, v)}>
          <SelectTrigger className="mt-0.5 h-7 text-xs">
            <SelectValue placeholder="Seleccionar…" />
          </SelectTrigger>
          <SelectContent>
            {choices.map((c) => (
              <SelectItem key={c} value={c} className="text-xs">
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  if (field_type === "multiselect") {
    let selected: string[] = [];
    if (value) {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed))
          selected = parsed.filter((v): v is string => typeof v === "string");
      } catch {
        selected = [];
      }
    }
    const toggle = (choice: string) => {
      const next = selected.includes(choice)
        ? selected.filter((s) => s !== choice)
        : [...selected, choice];
      onChange(key, next.length > 0 ? JSON.stringify(next) : null);
    };
    return (
      <div>
        <Label className="text-[11px]">{label}</Label>
        <div className="mt-0.5 flex flex-wrap gap-1">
          {choices.length === 0 ? (
            <span className="text-[10px] text-muted-foreground">
              (sin opciones)
            </span>
          ) : (
            choices.map((c) => {
              const checked = selected.includes(c);
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggle(c)}
                  aria-pressed={checked}
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[11px] transition-colors",
                    checked
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-muted text-muted-foreground hover:border-primary/40",
                  )}
                >
                  {c}
                </button>
              );
            })
          )}
        </div>
      </div>
    );
  }

  if (field_type === "checkbox") {
    const checked = value === "true";
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(key, checked ? "false" : "true")}
          aria-pressed={checked}
          className={cn(
            "flex h-4 w-4 shrink-0 items-center justify-center rounded border text-xs transition-colors",
            checked
              ? "border-primary bg-primary text-primary-foreground"
              : "border-input hover:border-primary/60",
          )}
        >
          {checked && <Check className="h-2.5 w-2.5" />}
        </button>
        <Label className="text-[11px] cursor-pointer">{label}</Label>
      </div>
    );
  }

  const inputType =
    field_type === "number"
      ? "number"
      : field_type === "date"
        ? "date"
        : "text";

  return (
    <div>
      <Label className="text-[11px]">{label}</Label>
      <Input
        type={inputType}
        value={value}
        onChange={(e) => onChange(key, e.target.value)}
        className="mt-0.5 h-7 text-xs"
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// NotesSection — full logic preserved, improved visuals
// ─────────────────────────────────────────────────────────────────────────────

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
            <span className="text-[10px] text-muted-foreground">
              Ctrl+Enter para guardar
            </span>
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

function NoteCard({
  note,
  customerId,
}: {
  note: CustomerNote;
  customerId: string;
}) {
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
    updateNote.mutate(
      { noteId: note.id, content: text },
      { onSuccess: () => setEditing(false) },
    );
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
        note.pinned
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-border bg-card",
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-1">
        <div className="flex flex-wrap items-center gap-x-1 min-w-0">
          <span className="font-medium truncate max-w-[100px]">
            {note.author_email?.split("@")[0] ?? "Sistema"}
          </span>
          <span className="text-[10px] text-muted-foreground shrink-0">
            · {relativeTime}
          </span>
          {wasEdited && (
            <span className="text-[10px] text-muted-foreground shrink-0">
              · editada
            </span>
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
            {note.pinned ? (
              <PinOff className="h-3 w-3" />
            ) : (
              <Pin className="h-3 w-3" />
            )}
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

// ─────────────────────────────────────────────────────────────────────────────
// Main export
// ─────────────────────────────────────────────────────────────────────────────

export function ContactPanel({ customerId, conversation }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const customer = useCustomerDetail(customerId ?? "");

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        aria-label="Expandir panel de contacto"
        className="flex h-full w-3 shrink-0 cursor-pointer items-center justify-center rounded-md border border-border bg-muted/40 transition-colors hover:bg-muted"
      >
        <ChevronLeft className="h-3 w-3 text-muted-foreground" />
      </button>
    );
  }

  return (
    <div className="flex w-80 shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground">
      {/* ── Panel header ─────────────────────────────────────────────── */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-xs font-semibold">Contacto</span>
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

      {/* ── Scrollable body ───────────────────────────────────────────── */}
      <ScrollArea className="flex-1">
        <div>
          {customerId ? (
            <>
              {/* Contact identity + score */}
              <ContactIdentitySection customerId={customerId} />

              {/* Quick actions */}
              {customer.data && (
                <QuickActionsSection phone={customer.data.phone_e164} />
              )}

              {/* Conversation meta */}
              {conversation && (
                <>
                  <Separator />
                  <ConversationSummarySection conversation={conversation} />
                </>
              )}

              {/* Custom fields */}
              <Separator />
              <CustomFieldsSection customerId={customerId} />

              {/* Notes */}
              <Separator />
              <NotesSection
                customerId={customerId}
                conversationId={conversation?.id}
              />
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

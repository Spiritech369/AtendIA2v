import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  BookOpen,
  Braces,
  FileText,
  GitBranch,
  GripVertical,
  Hash,
  Save,
  Search,
  UserRound,
  Workflow,
  Zap,
} from "lucide-react";
import { type DragEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { agentsApi } from "@/features/agents/api";
import { tenantsApi } from "@/features/config/api";
import { fieldsApi } from "@/features/customers/api";
import { knowledgeApi } from "@/features/knowledge/api";
import {
  FLOW_MODE_ALIAS_PLACEHOLDERS,
  FLOW_MODE_PURPOSES,
  FLOW_MODES,
  type FlowModeKey,
  type PipelineDraft,
  modeDisplayLabel,
  parsePipeline,
  serialisePipelineDraft,
} from "@/features/pipeline/components/PipelineEditor";
import { pipelineStagesApi, workflowsApi } from "@/features/workflows/api";
import { usersApi } from "@/features/users/api";
import { cn } from "@/lib/utils";

function cloneDraft(draft: PipelineDraft): PipelineDraft {
  return {
    ...draft,
    stages: draft.stages.map((stage) => ({ ...stage })),
    docs_per_plan: { ...draft.docs_per_plan },
    documents_catalog: draft.documents_catalog.map((doc) => ({ ...doc })),
    vision_doc_mapping: Object.fromEntries(
      Object.entries(draft.vision_doc_mapping).map(([key, value]) => [key, [...value]]),
    ),
    mode_prompts: { ...draft.mode_prompts },
    mode_labels: { ...draft.mode_labels },
    hidden_modes: [...draft.hidden_modes],
    extra: { ...draft.extra },
  };
}

type TokenGroup = "@" | "{{" | "/" | "#";
type TokenSource =
  | "users"
  | "agents"
  | "actions"
  | "fields"
  | "workflows"
  | "documents"
  | "faqs"
  | "stages"
  | "tags"
  | "lifecycle"
  | "pipeline";

interface PromptToken {
  group: TokenGroup;
  token: string;
  label: string;
  description: string;
  tone: string;
  source: TokenSource;
}

const INDUSTRY_TEMPLATES = [
  {
    id: "motos",
    title: "Motos",
    body: `Cotiza con precio contado, enganche, pago quincenal, plazo, liquidación anticipada sin penalización y documentos. Si falta modelo o precio, no inventes: pide el modelo exacto o envía catálogo.`,
  },
  {
    id: "clinica",
    title: "Clínica",
    body: `Responde con servicio, doctor, horario, precio de consulta, preparación y siguiente paso para cita. Si falta agenda o precio, pide el dato faltante o pasa a asesor.`,
  },
];

const TOKEN_TONES: Record<TokenGroup, string> = {
  "@": "bg-emerald-100/80 text-emerald-800 ring-emerald-300",
  "{{": "bg-blue-100/80 text-blue-800 ring-blue-300",
  "/": "bg-violet-100/80 text-violet-800 ring-violet-300",
  "#": "bg-amber-100/80 text-amber-800 ring-amber-300",
};

function tokenMatches(token: PromptToken, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    token.token.toLowerCase().includes(q) ||
    token.label.toLowerCase().includes(q) ||
    token.description.toLowerCase().includes(q)
  );
}

function tokenKey(token: string): string {
  return token.toLowerCase();
}

function tokenGroupFromText(text: string): TokenGroup | null {
  if (text.startsWith("{{")) return "{{";
  if (text.startsWith("@")) return "@";
  if (text.startsWith("/")) return "/";
  if (text.startsWith("#")) return "#";
  return null;
}

function renderHighlightedPrompt(text: string, knownTokens: Map<string, PromptToken>) {
  const pattern = /(\{\{contact\.[A-Za-z_][A-Za-z0-9_]*\}\}|@[A-Za-z][A-Za-z0-9_.-]*|\/[A-Za-z][A-Za-z0-9_.-]*|#[A-Za-z][A-Za-z0-9_.-]*)/g;
  const parts: Array<{ text: string; token?: PromptToken; group?: TokenGroup }> = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const value = match[0];
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ text: text.slice(cursor, index) });
    const token = knownTokens.get(tokenKey(value));
    parts.push({
      text: value,
      token,
      group: token ? token.group : tokenGroupFromText(value) ?? undefined,
    });
    cursor = index + value.length;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) });
  return parts;
}

function detectContext(text: string, cursor: number): { group: TokenGroup; from: number; query: string } | null {
  const before = text.slice(0, cursor);
  const doubleBrace = before.lastIndexOf("{{");
  const at = before.lastIndexOf("@");
  const slash = before.lastIndexOf("/");
  const hash = before.lastIndexOf("#");
  const candidates = [
    doubleBrace >= 0 ? { group: "{{" as const, from: doubleBrace, markerLength: 2 } : null,
    at >= 0 ? { group: "@" as const, from: at, markerLength: 1 } : null,
    slash >= 0 ? { group: "/" as const, from: slash, markerLength: 1 } : null,
    hash >= 0 ? { group: "#" as const, from: hash, markerLength: 1 } : null,
  ]
    .filter((x): x is { group: TokenGroup; from: number; markerLength: number } => x !== null)
    .sort((a, b) => b.from - a.from);
  const current = candidates[0];
  if (!current) return null;
  const query = before.slice(current.from + current.markerLength);
  if (/\s/.test(query) && current.group !== "{{") return null;
  if (current.group === "{{" && query.includes("}}")) return null;
  return { group: current.group, from: current.from, query };
}

const QUICK_ACTIONS: PromptToken[] = [
  {
    group: "/",
    token: "/asignar",
    label: "Asignar",
    description: "Asigna la conversación a usuario real o agente IA.",
    tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
    source: "actions",
  },
  {
    group: "/",
    token: "/desasignar",
    label: "Desasignar",
    description: "Quita responsable actual o manda a cola sin agente.",
    tone: "bg-rose-50 text-rose-700 border-rose-200",
    source: "actions",
  },
  {
    group: "/",
    token: "/detener_modo",
    label: "Detener modo",
    description: "Indica que el bot debe parar ese modo y esperar otra señal.",
    tone: "bg-amber-50 text-amber-700 border-amber-200",
    source: "actions",
  },
  {
    group: "/",
    token: "/enviar_documentos",
    label: "Enviar documentos",
    description: "Pide o envía checklist de documentos requeridos.",
    tone: "bg-sky-50 text-sky-700 border-sky-200",
    source: "actions",
  },
  {
    group: "/",
    token: "/actualizar_lifecycle",
    label: "Actualizar lifecycle",
    description: "Marca avance de ciclo de vida del lead/contacto.",
    tone: "bg-violet-50 text-violet-700 border-violet-200",
    source: "actions",
  },
];

const SYSTEM_ACTIONS: PromptToken[] = [
  {
    group: "@",
    token: "@Desasignar",
    label: "Desasignar",
    description: "Referencia especial: deja la conversacion sin usuario ni agente IA asignado.",
    tone: "bg-rose-50 text-rose-700 border-rose-200",
    source: "actions",
  },
  {
    group: "@",
    token: "@Action.Assign",
    label: "Acción: asignar",
    description: "Referencia una acción del sistema para asignación.",
    tone: "bg-slate-50 text-slate-700 border-slate-200",
    source: "actions",
  },
  {
    group: "@",
    token: "@Action.SendDocumentChecklist",
    label: "Acción: documentos",
    description: "Referencia la acción de documentos/checklist.",
    tone: "bg-slate-50 text-slate-700 border-slate-200",
    source: "actions",
  },
  {
    group: "@",
    token: "@Action.UpdateLifecycle",
    label: "Acción: lifecycle",
    description: "Referencia actualización de lifecycle.",
    tone: "bg-slate-50 text-slate-700 border-slate-200",
    source: "actions",
  },
];

const STATIC_HASH_REFERENCES: PromptToken[] = [
  "vip",
  "urgente",
  "manual",
  "nuevo",
  "calificado",
].map((tag) => ({
  group: "#" as const,
  token: `#tag.${tag}`,
  label: `Tag: ${tag}`,
  description: "Referencia de tag usada por conversaciones/clientes.",
  tone: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  source: "tags" as const,
}));

const LIFECYCLE_REFERENCES: PromptToken[] = [
  "new",
  "in_conversation",
  "qualified",
  "negotiation",
  "documentation",
  "pending_handoff",
  "closed_won",
  "closed_lost",
].map((stage) => ({
  group: "#" as const,
  token: `#lifecycle.${stage}`,
  label: `Lifecycle: ${stage}`,
  description: "Estados de cliente usados en Customers/Handoffs.",
  tone: "bg-indigo-50 text-indigo-700 border-indigo-200",
  source: "lifecycle" as const,
}));

const TOKEN_SECTIONS: Array<{
  id: TokenSource;
  title: string;
  icon: ReactNode;
  groups?: TokenGroup[];
}> = [
  { id: "users", title: "Usuarios", icon: <UserRound className="h-3.5 w-3.5" />, groups: ["@"] },
  { id: "agents", title: "Agentes IA", icon: <Bot className="h-3.5 w-3.5" />, groups: ["@"] },
  { id: "workflows", title: "Workflows", icon: <Workflow className="h-3.5 w-3.5" />, groups: ["/"] },
  { id: "actions", title: "Acciones", icon: <Zap className="h-3.5 w-3.5" />, groups: ["@", "/"] },
  {
    id: "fields",
    title: "Datos cliente",
    icon: <Braces className="h-3.5 w-3.5" />,
    groups: ["{{"],
  },
  { id: "documents", title: "Documentos KB", icon: <FileText className="h-3.5 w-3.5" />, groups: ["#"] },
  { id: "faqs", title: "FAQs KB", icon: <BookOpen className="h-3.5 w-3.5" />, groups: ["#"] },
  { id: "stages", title: "Pipeline", icon: <GitBranch className="h-3.5 w-3.5" />, groups: ["#"] },
  { id: "pipeline", title: "Config pipeline", icon: <GitBranch className="h-3.5 w-3.5" />, groups: ["#"] },
  { id: "tags", title: "Tags", icon: <Hash className="h-3.5 w-3.5" />, groups: ["#"] },
  { id: "lifecycle", title: "Lifecycle", icon: <GitBranch className="h-3.5 w-3.5" />, groups: ["#"] },
];

export function ComposerModesEditor() {
  const qc = useQueryClient();
  const textareaRefs = useRef<Partial<Record<FlowModeKey, HTMLTextAreaElement | null>>>({});
  const highlightRefs = useRef<Partial<Record<FlowModeKey, HTMLDivElement | null>>>({});
  const [activeMode, setActiveMode] = useState<FlowModeKey>("PLAN");
  const [cursorByMode, setCursorByMode] = useState<Partial<Record<FlowModeKey, number>>>({});
  const [tokenSearch, setTokenSearch] = useState("");
  const query = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
  });
  const [draft, setDraft] = useState<PipelineDraft | null>(null);
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: usersApi.list });
  const agentsQuery = useQuery({ queryKey: ["agents", "composer-context"], queryFn: agentsApi.list });
  const fieldsQuery = useQuery({
    queryKey: ["customer-fields", "definitions", "composer-context"],
    queryFn: fieldsApi.listDefinitions,
  });
  const docsQuery = useQuery({
    queryKey: ["knowledge", "documents", "composer-context"],
    queryFn: knowledgeApi.listDocuments,
  });
  const faqsQuery = useQuery({
    queryKey: ["knowledge", "faqs", "composer-context"],
    queryFn: knowledgeApi.listFaqs,
  });
  const stagesQuery = useQuery({
    queryKey: ["pipeline", "stages", "composer-context"],
    queryFn: pipelineStagesApi.list,
  });
  const workflowsQuery = useQuery({
    queryKey: ["workflows", "composer-context"],
    queryFn: workflowsApi.list,
  });

  useEffect(() => {
    if (query.data?.definition) setDraft(parsePipeline(query.data.definition));
  }, [query.data?.definition]);

  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("Sin pipeline cargado");
      return tenantsApi.putPipeline(serialisePipelineDraft(draft));
    },
    onSuccess: () => {
      toast.success("Composer guardado");
      void qc.invalidateQueries({ queryKey: ["tenants", "pipeline"] });
    },
    onError: (error) => toast.error("No se pudo guardar Composer", { description: error.message }),
  });

  const hiddenModeSet = useMemo(() => new Set(draft?.hidden_modes ?? []), [draft?.hidden_modes]);
  const configuredModeCount = FLOW_MODES.filter(
    (mode) => (draft?.mode_prompts?.[mode] ?? "").trim().length > 0,
  ).length;
  const visibleModeCount = FLOW_MODES.filter((mode) => !hiddenModeSet.has(mode)).length;

  const updateModeLabel = (mode: FlowModeKey, value: string) => {
    setDraft((current) => {
      if (!current) return current;
      const next = cloneDraft(current);
      if (value.trim()) next.mode_labels[mode] = value;
      else delete next.mode_labels[mode];
      return next;
    });
  };

  const updateModePrompt = (mode: FlowModeKey, value: string) => {
    setDraft((current) => {
      if (!current) return current;
      const next = cloneDraft(current);
      next.mode_prompts[mode] = value;
      return next;
    });
  };

  const setModeVisible = (mode: FlowModeKey, currentlyHidden: boolean) => {
    setDraft((current) => {
      if (!current) return current;
      const hidden = new Set(current.hidden_modes);
      if (currentlyHidden) hidden.delete(mode);
      else hidden.add(mode);
      return { ...cloneDraft(current), hidden_modes: FLOW_MODES.filter((m) => hidden.has(m)) };
    });
  };

  const syncCursor = (mode: FlowModeKey) => {
    const cursor = textareaRefs.current[mode]?.selectionStart ?? draft?.mode_prompts?.[mode]?.length ?? 0;
    setActiveMode(mode);
    setCursorByMode((current) => ({ ...current, [mode]: cursor }));
  };

  const syncScroll = (mode: FlowModeKey) => {
    const textarea = textareaRefs.current[mode];
    const highlight = highlightRefs.current[mode];
    if (!textarea || !highlight) return;
    highlight.scrollTop = textarea.scrollTop;
    highlight.scrollLeft = textarea.scrollLeft;
  };

  const contextualTokens = useMemo<PromptToken[]>(() => {
    const users =
      usersQuery.data
        ?.filter((user) => user.email.toLowerCase() !== "desasignar@system.local")
        .map((user) => ({
          group: "@" as const,
          token: `@user.${user.email}`,
          label: user.email,
          description: `Usuario real (${user.role})`,
          tone: "bg-emerald-50 text-emerald-700 border-emerald-200",
          source: "users" as const,
        })) ?? [];
    const agents =
      agentsQuery.data?.map((agent) => ({
        group: "@" as const,
        token: `@agent.${agent.name.replace(/\s+/g, "_")}`,
        label: agent.name,
        description: `Agente IA (${agent.status})`,
        tone: "bg-violet-50 text-violet-700 border-violet-200",
        source: "agents" as const,
      })) ?? [];
    const documents =
      docsQuery.data?.slice(0, 20).map((document) => ({
        group: "#" as const,
        token: `#document.${document.filename.replace(/\s+/g, "_")}`,
        label: document.filename,
        description: `Documento KB/RAG (${document.status}, ${document.fragment_count} chunks)`,
        tone: "bg-amber-50 text-amber-700 border-amber-200",
        source: "documents" as const,
      })) ?? [];
    const faqs =
      faqsQuery.data?.slice(0, 20).map((faq) => ({
        group: "#" as const,
        token: `#faq.${faq.id}`,
        label: faq.question,
        description: "FAQ de Knowledge Base/RAG.",
        tone: "bg-cyan-50 text-cyan-700 border-cyan-200",
        source: "faqs" as const,
      })) ?? [];
    const contactFields =
      fieldsQuery.data?.map((field) => ({
        group: "{{" as const,
        token: `{{contact.${field.key}}}`,
        label: field.label,
        description: `Dato cliente: ${field.key} (${field.field_type})`,
        tone: "bg-blue-50 text-blue-700 border-blue-200",
        source: "fields" as const,
      })) ?? [];
    const stages =
      stagesQuery.data?.map((stage) => ({
        group: "#" as const,
        token: `#stage.${stage.id}`,
        label: stage.label,
        description: "Etapa del pipeline activo.",
        tone: "bg-sky-50 text-sky-700 border-sky-200",
        source: "stages" as const,
      })) ?? [];
    const workflows =
      workflowsQuery.data?.map((workflow) => ({
        group: "/" as const,
        token: `/workflow.${workflow.name.replace(/\s+/g, "_")}`,
        label: workflow.name,
        description: `Ejecuta workflow (${workflow.status}, v${workflow.version})`,
        tone: "bg-violet-50 text-violet-700 border-violet-200",
        source: "workflows" as const,
      })) ?? [];
    const pipelineReferences: PromptToken[] = [
      {
        group: "#",
        token: "#pipeline.active",
        label: "Pipeline activo",
        description: "Referencia al pipeline activo de este tenant.",
        tone: "bg-slate-50 text-slate-700 border-slate-200",
        source: "pipeline",
      },
      {
        group: "#",
        token: "#pipeline.mode_prompts",
        label: "Guiones Composer",
        description: "Bloque de guiones por modo del pipeline.",
        tone: "bg-slate-50 text-slate-700 border-slate-200",
        source: "pipeline",
      },
    ];
    return [
      ...users,
      ...agents,
      ...SYSTEM_ACTIONS,
      ...QUICK_ACTIONS,
      ...contactFields,
      ...workflows,
      ...documents,
      ...faqs,
      ...stages,
      ...STATIC_HASH_REFERENCES,
      ...LIFECYCLE_REFERENCES,
      ...pipelineReferences,
    ];
  }, [
    agentsQuery.data,
    docsQuery.data,
    faqsQuery.data,
    fieldsQuery.data,
    stagesQuery.data,
    usersQuery.data,
    workflowsQuery.data,
  ]);

  const activePrompt = draft?.mode_prompts?.[activeMode] ?? "";
  const activeContext = detectContext(activePrompt, cursorByMode[activeMode] ?? activePrompt.length);
  const filteredTokens = contextualTokens
    .filter((token) => (activeContext ? token.group === activeContext.group : true))
    .filter((token) => tokenMatches(token, activeContext?.query || tokenSearch))
    .filter((token) => tokenMatches(token, tokenSearch));
  const visibleTokens = filteredTokens.slice(0, activeContext ? 12 : 60);
  const knownTokens = useMemo(
    () => new Map(contextualTokens.map((token) => [tokenKey(token.token), token])),
    [contextualTokens],
  );

  const insertToken = (token: PromptToken, dropCursor?: number, targetMode = activeMode) => {
    if (!draft) return;
    const textarea = textareaRefs.current[targetMode];
    const value = draft.mode_prompts?.[targetMode] ?? "";
    const cursor = dropCursor ?? textarea?.selectionStart ?? value.length;
    const context = detectContext(value, cursor);
    const from = context?.group === token.group ? context.from : cursor;
    const nextValue = `${value.slice(0, from)}${token.token}${value.slice(cursor)}`;
    updateModePrompt(targetMode, nextValue);
    requestAnimationFrame(() => {
      const nextCursor = from + token.token.length;
      textareaRefs.current[targetMode]?.focus();
      textareaRefs.current[targetMode]?.setSelectionRange(nextCursor, nextCursor);
      setCursorByMode((current) => ({ ...current, [targetMode]: nextCursor }));
    });
  };

  const insertIndustryTemplate = (body: string) => {
    const current = draft?.mode_prompts?.[activeMode] ?? "";
    updateModePrompt(activeMode, current.trim() ? `${current.trim()}\n\n${body}` : body);
    requestAnimationFrame(() => textareaRefs.current[activeMode]?.focus());
  };

  const insertDroppedToken = (mode: FlowModeKey, event: DragEvent<HTMLTextAreaElement>) => {
    const tokenValue = event.dataTransfer.getData("text/plain");
    const token = contextualTokens.find((item) => item.token === tokenValue);
    if (!token) return;
    event.preventDefault();
    setActiveMode(mode);
    const textarea = textareaRefs.current[mode];
    const cursor =
      textarea && typeof textarea.selectionStart === "number"
        ? textarea.selectionStart
        : (draft?.mode_prompts?.[mode] ?? "").length;
    setCursorByMode((current) => ({ ...current, [mode]: cursor }));
    insertToken(token, cursor, mode);
  };

  if (query.isLoading) return <Skeleton className="h-96 w-full" />;

  if (!draft) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          No hay pipeline activo todavía. Crea uno para configurar los modos del Composer.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Comportamiento de la IA</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Modos de respuesta, tono, reglas de seguridad, datos que puede usar y pruebas.
          </p>
        </div>
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          <Save className="mr-1.5 h-4 w-4" />
          {save.isPending ? "Guardando..." : "Guardar comportamiento"}
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Modos configurados ({configuredModeCount}/6 configurados · {visibleModeCount}/6
              visibles)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-md border bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">
              <strong className="text-foreground">Tokens del prompt.</strong> Escribe{" "}
              <code>@</code>, <code>{"{{"}</code>, <code>/</code> o <code>#</code> dentro del
              prompt para filtrar el panel contextual y seleccionar referencias reales.
            </div>

            {FLOW_MODES.map((mode) => {
              const hidden = hiddenModeSet.has(mode);
              return (
                <div
                  key={mode}
                  className={cn(
                    "space-y-3 rounded-md border bg-muted/10 p-3",
                    hidden && "bg-muted/5 opacity-75",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <code className="rounded bg-background px-1.5 py-0.5 text-xs">{mode}</code>
                        <span className="text-sm font-medium">{modeDisplayLabel(draft, mode)}</span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Uso base: {FLOW_MODE_PURPOSES[mode]}.
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={!hidden}
                      onClick={() => setModeVisible(mode, hidden)}
                      className={cn(
                        "relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        hidden ? "bg-muted" : "bg-primary",
                      )}
                      title={hidden ? "Mostrar modo" : "Ocultar modo no usado"}
                    >
                      <span
                        className={cn(
                          "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow transition-transform",
                          hidden ? "translate-x-0" : "translate-x-5",
                        )}
                      />
                    </button>
                  </div>

                  <div className="space-y-3">
                    <div className="max-w-xl space-y-1.5">
                      <Label htmlFor={`composer-label-${mode}`}>Nombre visible</Label>
                      <Input
                        id={`composer-label-${mode}`}
                        value={draft.mode_labels?.[mode] ?? ""}
                        onChange={(event) => updateModeLabel(mode, event.target.value)}
                        placeholder={FLOW_MODE_ALIAS_PLACEHOLDERS[mode]}
                      />
                    </div>
                    {hidden ? (
                      <div className="flex items-center rounded-md border border-dashed bg-background/40 px-3 py-2 text-xs text-muted-foreground">
                        Oculto en el editor y selectores. No borra su prompt ni invalida etapas
                        existentes que ya lo usen.
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        <Label htmlFor={`composer-prompt-${mode}`}>Instrucciones para este modo</Label>
                        <div className="grid min-h-[720px] w-full rounded-md border bg-background focus-within:ring-2 focus-within:ring-ring">
                          <div
                            ref={(node) => {
                              highlightRefs.current[mode] = node;
                            }}
                            aria-hidden="true"
                            className="pointer-events-none col-start-1 row-start-1 min-h-[720px] whitespace-pre-wrap break-words p-3 text-sm leading-6 text-foreground"
                          >
                            {(draft.mode_prompts?.[mode] ?? "").length === 0 ? (
                              <span className="text-muted-foreground">
                                Vacio = guion generico neutral para este modo
                              </span>
                            ) : (
                              renderHighlightedPrompt(
                                draft.mode_prompts?.[mode] ?? "",
                                knownTokens,
                              ).map((part, index) =>
                                part.token ? (
                                  <span
                                    key={`${part.text}-${index}`}
                                    className={cn(
                                      "rounded-sm ring-1",
                                      TOKEN_TONES[part.token.group],
                                    )}
                                    title={part.token.description}
                                  >
                                    {part.text}
                                  </span>
                                ) : (
                                  <span key={`${part.text}-${index}`}>{part.text}</span>
                                ),
                              )
                            )}
                          </div>
                          <textarea
                            ref={(node) => {
                              textareaRefs.current[mode] = node;
                            }}
                            id={`composer-prompt-${mode}`}
                            rows={28}
                            value={draft.mode_prompts?.[mode] ?? ""}
                            onFocus={() => syncCursor(mode)}
                            onClick={() => syncCursor(mode)}
                            onKeyUp={() => syncCursor(mode)}
                            onSelect={() => syncCursor(mode)}
                            onScroll={() => syncScroll(mode)}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={(event) => insertDroppedToken(mode, event)}
                            onChange={(event) => {
                              setActiveMode(mode);
                              updateModePrompt(mode, event.target.value);
                              setCursorByMode((current) => ({
                                ...current,
                                [mode]: event.target.selectionStart ?? event.target.value.length,
                              }));
                            }}
                            className="relative z-10 col-start-1 row-start-1 h-full min-h-[720px] w-full resize-none overflow-hidden bg-transparent p-3 text-sm leading-6 text-transparent caret-foreground outline-none selection:bg-primary/20"
                          />
                        </div>
                        <div className="hidden rounded-md border bg-muted/20 p-3">
                          <div className="mb-2 text-[11px] font-medium text-muted-foreground">
                            Referencias detectadas
                          </div>
                          <div className="max-h-36 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
                            {renderHighlightedPrompt(draft.mode_prompts?.[mode] ?? "", knownTokens).map(
                              (part, index) =>
                                part.token ? (
                                  <span
                                    key={`${part.text}-${index}`}
                                    className="rounded bg-blue-50 px-1 font-mono font-medium text-blue-700 ring-1 ring-blue-200"
                                    title={part.token.description}
                                  >
                                    {part.text}
                                  </span>
                                ) : (
                                  <span key={`${part.text}-${index}`}>{part.text}</span>
                                ),
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card className="xl:sticky xl:top-4 xl:self-start">
          <CardHeader>
            <CardTitle className="text-base">Autocomplete contextual</CardTitle>
            <div className="text-xs text-muted-foreground">
              Activo en {activeMode}. Escribe @, {"{{"}, / o # dentro del prompt.
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={tokenSearch}
                onChange={(event) => setTokenSearch(event.target.value)}
                placeholder="Buscar referencias reales..."
                className="h-8 pl-8 text-xs"
              />
            </div>
            <div className="space-y-1.5 rounded-md border bg-muted/20 p-2">
              <div className="text-xs font-medium text-muted-foreground">
                Plantillas por industria
              </div>
              {INDUSTRY_TEMPLATES.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  onClick={() => insertIndustryTemplate(template.body)}
                  className="w-full rounded-md border bg-background p-2 text-left transition-colors hover:bg-muted/50"
                >
                  <div className="text-xs font-medium">{template.title}</div>
                  <div className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">
                    {template.body}
                  </div>
                </button>
              ))}
            </div>
            <div className="max-h-[calc(100vh-16rem)] space-y-3 overflow-auto pr-1">
              {TOKEN_SECTIONS.map((section) => {
                const tokens = visibleTokens.filter((token) => token.source === section.id);
                if (tokens.length === 0) return null;
                return (
                  <div key={section.id} className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
                      <span className="inline-flex items-center gap-1.5">
                        {section.icon}
                        {section.title}
                      </span>
                      <Badge variant="secondary" className="h-5 rounded-sm px-1.5 text-[10px]">
                        {tokens.length}
                      </Badge>
                    </div>
                    {tokens.map((token) => (
                      <button
                        key={`${token.group}-${token.token}`}
                        type="button"
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.setData("text/plain", token.token);
                          event.dataTransfer.effectAllowed = "copy";
                        }}
                        onClick={() => insertToken(token)}
                        className="group w-full rounded-md border bg-background p-2 text-left transition-colors hover:bg-muted/50"
                        title="Clic para insertar o arrastra al prompt"
                      >
                        <div className="flex items-start gap-2">
                          <GripVertical className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-60 group-hover:opacity-100" />
                          <div className="min-w-0 flex-1">
                            <Badge
                              variant="outline"
                              className={cn("mb-1 max-w-full truncate font-mono", token.tone)}
                            >
                              {token.token}
                            </Badge>
                            <div className="truncate text-xs font-medium">{token.label}</div>
                            <div className="line-clamp-2 text-[11px] text-muted-foreground">
                              {token.description}
                            </div>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
            <div className="rounded-md bg-slate-950 p-3 text-[11px] text-slate-100">
              @ = usuarios/agentes · {"{{ }}"} = datos cliente · / = workflows · # =
              documentos/FAQ/etapas/tags/lifecycle
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

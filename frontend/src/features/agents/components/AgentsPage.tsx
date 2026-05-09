import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Loader2,
  Play,
  Plus,
  Send,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { agentsApi, type AgentItem } from "@/features/agents/api";

const ROLES = ["sales", "support", "collections", "documentation", "reception", "custom"] as const;
const ROLE_LABEL: Record<string, string> = {
  sales: "Ventas",
  support: "Soporte",
  collections: "Cobranza",
  documentation: "Documentación",
  reception: "Recepción",
  custom: "Personalizado",
};
const ROLE_COLOR: Record<string, string> = {
  sales: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  support: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  collections: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  documentation: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  reception: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  custom: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300",
};

const TONES = ["formal", "neutral", "amigable", "entusiasta", "casual"] as const;
const LANGUAGES = [
  { value: "es", label: "Español" },
  { value: "en", label: "English" },
  { value: "both", label: "Ambos" },
] as const;

// Mirror of NLU_INTENTS in backend agents_routes.py — keep in sync.
const INTENTS = [
  "GREETING",
  "ASK_INFO",
  "ASK_PRICE",
  "BUY",
  "SCHEDULE",
  "COMPLAIN",
  "OFF_TOPIC",
  "UNCLEAR",
] as const;

const FIELD_TYPES = ["text", "number", "date", "select", "boolean"] as const;

interface ExtractionField {
  key: string;
  label: string;
  type: (typeof FIELD_TYPES)[number];
  description?: string;
  required?: boolean;
}

interface AutoActions {
  close_keywords: string[];
  handoff_keywords: string[];
  trigger_workflows: Record<string, string[]>;
}

interface KnowledgeConfig {
  strict_ks: boolean;
  structured_enabled: boolean;
  semi_structured_enabled: boolean;
  free_text_enabled: boolean;
}

interface MemoryRules {
  enabled: boolean;
  max_history_messages: number;
  learn_from_customers: boolean;
  learn_from_human_feedback: boolean;
}

function asExtractionFields(value: unknown): ExtractionField[] {
  if (!value || typeof value !== "object") return [];
  const fields = (value as Record<string, unknown>).fields;
  if (!Array.isArray(fields)) return [];
  return fields
    .filter((f): f is Record<string, unknown> => typeof f === "object" && f !== null)
    .map((f) => ({
      key: String(f.key ?? ""),
      label: String(f.label ?? f.key ?? ""),
      type: (FIELD_TYPES as readonly string[]).includes(String(f.type))
        ? (f.type as ExtractionField["type"])
        : "text",
      description: typeof f.description === "string" ? f.description : "",
      required: Boolean(f.required),
    }));
}

function asAutoActions(value: unknown): AutoActions {
  const v = (value as Record<string, unknown>) ?? {};
  const close = Array.isArray(v.close_keywords) ? v.close_keywords.map(String) : [];
  const handoff = Array.isArray(v.handoff_keywords) ? v.handoff_keywords.map(String) : [];
  const triggers: Record<string, string[]> = {};
  if (v.trigger_workflows && typeof v.trigger_workflows === "object") {
    for (const [k, val] of Object.entries(v.trigger_workflows as Record<string, unknown>)) {
      if (Array.isArray(val)) triggers[k] = val.map(String);
    }
  }
  return { close_keywords: close, handoff_keywords: handoff, trigger_workflows: triggers };
}

function asKnowledgeConfig(value: unknown): KnowledgeConfig {
  const v = (value as Record<string, unknown>) ?? {};
  return {
    strict_ks: v.strict_ks !== false,
    structured_enabled: v.structured_enabled !== false,
    semi_structured_enabled: v.semi_structured_enabled !== false,
    free_text_enabled: v.free_text_enabled !== false,
  };
}

function asMemoryRules(value: unknown): MemoryRules {
  const v = (value as Record<string, unknown>) ?? {};
  return {
    enabled: v.enabled !== false,
    max_history_messages: typeof v.max_history_messages === "number" ? v.max_history_messages : 20,
    learn_from_customers: v.learn_from_customers !== false,
    learn_from_human_feedback: v.learn_from_human_feedback !== false,
  };
}

export function AgentsPage() {
  const qc = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: agentsApi.list });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId && agents.data && agents.data.length > 0) {
      setSelectedId(agents.data[0]?.id ?? null);
    }
  }, [agents.data, selectedId]);

  const create = useMutation({
    mutationFn: () =>
      agentsApi.create({
        name: "Nuevo agente",
        role: "custom",
        active_intents: [],
        is_default: (agents.data?.length ?? 0) === 0,
      }),
    onSuccess: (agent) => {
      setSelectedId(agent.id);
      void qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agente creado");
    },
    onError: (e) => toast.error("No se pudo crear", { description: e.message }),
  });

  const remove = useMutation({
    mutationFn: agentsApi.delete,
    onSuccess: () => {
      setSelectedId(null);
      void qc.invalidateQueries({ queryKey: ["agents"] });
      toast.success("Agente eliminado");
    },
    onError: (e) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  const selected = agents.data?.find((a) => a.id === selectedId) ?? null;

  return (
    <div className="grid h-full gap-4 xl:grid-cols-[300px_1fr]">
      <Card className="h-fit">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 py-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Bot className="h-4 w-4" /> Agentes IA
          </CardTitle>
          <Button size="sm" onClick={() => create.mutate()} disabled={create.isPending}>
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          {agents.isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : (agents.data ?? []).length === 0 ? (
            <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
              No hay agentes todavía. Crea uno para empezar.
            </div>
          ) : (
            (agents.data ?? []).map((agent) => (
              <button
                key={agent.id}
                type="button"
                onClick={() => setSelectedId(agent.id)}
                className={`w-full rounded-md border p-3 text-left text-sm transition-colors ${
                  selectedId === agent.id ? "border-primary bg-muted" : "hover:bg-muted/50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{agent.name}</span>
                  {agent.is_default && (
                    <Star className="h-3.5 w-3.5 shrink-0 fill-amber-400 text-amber-400" />
                  )}
                </div>
                <div className="mt-1 flex items-center gap-1">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${ROLE_COLOR[agent.role] ?? ""}`}>
                    {ROLE_LABEL[agent.role] ?? agent.role}
                  </span>
                  {agent.active_intents.length > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      {agent.active_intents.length} intents
                    </span>
                  )}
                </div>
              </button>
            ))
          )}
        </CardContent>
      </Card>
      {selected ? (
        <AgentEditor
          key={selected.id}
          agent={selected}
          onDelete={() => {
            if (confirm(`¿Eliminar agente "${selected.name}"?`)) remove.mutate(selected.id);
          }}
        />
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Bot className="h-10 w-10 text-muted-foreground" />
            <div className="text-sm font-medium">Selecciona o crea un agente</div>
            <div className="text-xs text-muted-foreground">
              Cada agente puede tener un rol, prompt e intenciones específicas.
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function AgentEditor({ agent, onDelete }: { agent: AgentItem; onDelete: () => void }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<AgentItem>(agent);

  useEffect(() => setDraft(agent), [agent]);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(agent), [draft, agent]);

  const save = useMutation({
    mutationFn: () =>
      agentsApi.patch(agent.id, {
        name: draft.name,
        role: draft.role,
        goal: draft.goal,
        style: draft.style,
        tone: draft.tone,
        language: draft.language,
        max_sentences: draft.max_sentences,
        no_emoji: draft.no_emoji,
        return_to_flow: draft.return_to_flow,
        is_default: draft.is_default,
        system_prompt: draft.system_prompt,
        active_intents: draft.active_intents,
        extraction_config: draft.extraction_config,
        auto_actions: draft.auto_actions,
        knowledge_config: draft.knowledge_config,
        flow_mode_rules: draft.flow_mode_rules,
      }),
    onSuccess: () => {
      toast.success("Agente guardado");
      void qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (e) => toast.error("No se pudo guardar", { description: e.message }),
  });

  const update = <K extends keyof AgentItem>(key: K, value: AgentItem[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const toggleIntent = (intent: string) => {
    const present = draft.active_intents.includes(intent);
    update(
      "active_intents",
      present ? draft.active_intents.filter((i) => i !== intent) : [...draft.active_intents, intent],
    );
  };

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div className="min-w-0 flex-1">
          <Input
            value={draft.name}
            onChange={(e) => update("name", e.target.value)}
            className="border-none bg-transparent px-0 text-lg font-semibold shadow-none focus-visible:ring-0"
          />
          <div className="mt-1 flex items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${ROLE_COLOR[draft.role] ?? ""}`}>
              {ROLE_LABEL[draft.role] ?? draft.role}
            </span>
            {draft.is_default && <Badge variant="outline">Default</Badge>}
            {dirty && <span className="text-[11px] text-amber-600 dark:text-amber-400">Cambios sin guardar</span>}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button onClick={() => save.mutate()} disabled={save.isPending || !dirty}>
            {save.isPending ? "Guardando..." : "Guardar"}
          </Button>
          <Button variant="ghost" size="icon" onClick={onDelete} title="Eliminar">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="identity">
          <TabsList>
            <TabsTrigger value="identity">Identidad</TabsTrigger>
            <TabsTrigger value="data">Datos</TabsTrigger>
            <TabsTrigger value="actions">Acciones</TabsTrigger>
            <TabsTrigger value="knowledge">Conocimiento</TabsTrigger>
            <TabsTrigger value="memory">Memoria</TabsTrigger>
            <TabsTrigger value="test">Probar</TabsTrigger>
          </TabsList>
          <TabsContent value="identity" className="mt-4">
            <IdentityTab draft={draft} update={update} toggleIntent={toggleIntent} />
          </TabsContent>
          <TabsContent value="data" className="mt-4">
            <DataTab
              fields={asExtractionFields(draft.extraction_config)}
              onChange={(fields) =>
                update("extraction_config", { ...(draft.extraction_config ?? {}), fields })
              }
            />
          </TabsContent>
          <TabsContent value="actions" className="mt-4">
            <ActionsTab
              actions={asAutoActions(draft.auto_actions)}
              onChange={(next) =>
                update("auto_actions", { ...(draft.auto_actions ?? {}), ...next })
              }
            />
          </TabsContent>
          <TabsContent value="knowledge" className="mt-4">
            <KnowledgeTab
              config={asKnowledgeConfig(draft.knowledge_config)}
              onChange={(next) =>
                update("knowledge_config", { ...(draft.knowledge_config ?? {}), ...next })
              }
            />
          </TabsContent>
          <TabsContent value="memory" className="mt-4">
            <MemoryTab
              rules={asMemoryRules(draft.flow_mode_rules)}
              onChange={(next) =>
                update("flow_mode_rules", { ...(draft.flow_mode_rules ?? {}), ...next })
              }
            />
          </TabsContent>
          <TabsContent value="test" className="mt-4">
            <TestTab agent={draft} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function IdentityTab({
  draft,
  update,
  toggleIntent,
}: {
  draft: AgentItem;
  update: <K extends keyof AgentItem>(key: K, value: AgentItem[K]) => void;
  toggleIntent: (intent: string) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Identidad</h3>
        <div>
          <Label>Rol</Label>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {ROLES.map((role) => (
              <button
                key={role}
                type="button"
                onClick={() => update("role", role)}
                className={`rounded-md border px-2.5 py-1 text-xs ${
                  draft.role === role ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
              >
                {ROLE_LABEL[role]}
              </button>
            ))}
          </div>
        </div>
        <div>
          <Label>Objetivo principal</Label>
          <Input
            value={draft.goal ?? ""}
            onChange={(e) => update("goal", e.target.value || null)}
            placeholder="Ej. convertir leads en ventas lo más rápido posible"
          />
        </div>
        <div>
          <Label>Estilo</Label>
          <Input
            value={draft.style ?? ""}
            onChange={(e) => update("style", e.target.value || null)}
            placeholder="Ej. informal, breve, comercial, directo"
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <Label>Max. oraciones</Label>
            <Input
              type="number"
              min={1}
              max={20}
              value={draft.max_sentences ?? 5}
              onChange={(e) => update("max_sentences", Number(e.target.value || 5))}
            />
          </div>
          <label className="mt-6 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={draft.no_emoji}
              onChange={(e) => update("no_emoji", e.target.checked)}
            />
            Sin emojis
          </label>
          <label className="mt-6 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={draft.return_to_flow}
              onChange={(e) => update("return_to_flow", e.target.checked)}
            />
            Volver al flujo
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.is_default}
            onChange={(e) => update("is_default", e.target.checked)}
          />
          Agente por defecto
        </label>
      </div>
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Comportamiento IA</h3>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label>Tono</Label>
            <Select value={draft.tone ?? "amigable"} onValueChange={(v) => update("tone", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TONES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Idioma</Label>
            <Select value={draft.language ?? "es"} onValueChange={(v) => update("language", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANGUAGES.map((l) => (
                  <SelectItem key={l.value} value={l.value}>
                    {l.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div>
          <Label>System prompt</Label>
          <Textarea
            value={draft.system_prompt ?? ""}
            onChange={(e) => update("system_prompt", e.target.value || null)}
            rows={6}
            placeholder="Eres un agente especialista en..."
          />
        </div>
        <div>
          <Label>Intenciones activas</Label>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {INTENTS.map((intent) => {
              const active = draft.active_intents.includes(intent);
              return (
                <button
                  key={intent}
                  type="button"
                  onClick={() => toggleIntent(intent)}
                  className={`rounded px-2 py-1 font-mono text-[10px] ${
                    active
                      ? "border border-primary bg-primary/10 text-primary"
                      : "border border-transparent bg-muted text-muted-foreground hover:bg-muted/70"
                  }`}
                >
                  {intent}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function DataTab({
  fields,
  onChange,
}: {
  fields: ExtractionField[];
  onChange: (fields: ExtractionField[]) => void;
}) {
  const update = (idx: number, patch: Partial<ExtractionField>) => {
    onChange(fields.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  };
  const remove = (idx: number) => onChange(fields.filter((_, i) => i !== idx));
  const add = () =>
    onChange([
      ...fields,
      { key: `campo_${fields.length + 1}`, label: "Nuevo campo", type: "text", required: false },
    ]);

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Campos que el agente intentará extraer de la conversación. Se guardan en el cliente para uso del CRM.
      </p>
      <div className="space-y-2">
        {fields.length === 0 && (
          <div className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
            No hay campos definidos. Agrega uno para que el agente empiece a extraerlo.
          </div>
        )}
        {fields.map((f, idx) => (
          <div key={idx} className="grid items-start gap-2 rounded-md border p-2 md:grid-cols-[1fr_1fr_140px_1fr_auto]">
            <Input
              value={f.key}
              onChange={(e) => update(idx, { key: e.target.value })}
              placeholder="clave"
              className="font-mono text-xs"
            />
            <Input
              value={f.label}
              onChange={(e) => update(idx, { label: e.target.value })}
              placeholder="Etiqueta"
            />
            <Select value={f.type} onValueChange={(v) => update(idx, { type: v as ExtractionField["type"] })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FIELD_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={f.description ?? ""}
              onChange={(e) => update(idx, { description: e.target.value })}
              placeholder="Pista para extracción"
            />
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-[10px]">
                <input
                  type="checkbox"
                  checked={f.required ?? false}
                  onChange={(e) => update(idx, { required: e.target.checked })}
                />
                req.
              </label>
              <Button variant="ghost" size="icon" onClick={() => remove(idx)} title="Eliminar">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        ))}
      </div>
      <Button variant="outline" size="sm" onClick={add}>
        <Plus className="mr-1 h-3.5 w-3.5" /> Agregar campo
      </Button>
    </div>
  );
}

function ActionsTab({
  actions,
  onChange,
}: {
  actions: AutoActions;
  onChange: (next: Partial<AutoActions>) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <Label>Palabras que cierran la conversación</Label>
        <ChipInput
          values={actions.close_keywords}
          onChange={(values) => onChange({ close_keywords: values })}
          placeholder="ya no quiero, no gracias, más adelante…"
        />
      </div>
      <div>
        <Label>Palabras que escalan a un humano</Label>
        <ChipInput
          values={actions.handoff_keywords}
          onChange={(values) => onChange({ handoff_keywords: values })}
          placeholder="humano, asesor, persona…"
        />
      </div>
      <div>
        <Label>Triggers de workflow por palabra clave</Label>
        <p className="mt-1 text-xs text-muted-foreground">
          Cuando el cliente menciona una de estas frases, se ejecuta el workflow indicado.
        </p>
        <TriggerWorkflowsEditor
          triggers={actions.trigger_workflows}
          onChange={(trigger_workflows) => onChange({ trigger_workflows })}
        />
      </div>
    </div>
  );
}

function ChipInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const commit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (values.includes(trimmed)) {
      setText("");
      return;
    }
    onChange([...values, trimmed]);
    setText("");
  };
  return (
    <div className="mt-1">
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && text === "" && values.length > 0) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={commit}
        placeholder={placeholder}
      />
      {values.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
            >
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function TriggerWorkflowsEditor({
  triggers,
  onChange,
}: {
  triggers: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
}) {
  const entries = Object.entries(triggers);
  const [newKey, setNewKey] = useState("");

  const updateKey = (oldKey: string, newKeyValue: string) => {
    if (!newKeyValue.trim() || newKeyValue === oldKey) return;
    const next: Record<string, string[]> = {};
    for (const [k, v] of entries) {
      next[k === oldKey ? newKeyValue : k] = v;
    }
    onChange(next);
  };

  const updateValues = (key: string, values: string[]) => {
    onChange({ ...triggers, [key]: values });
  };

  const remove = (key: string) => {
    const next = { ...triggers };
    delete next[key];
    onChange(next);
  };

  const add = () => {
    const key = newKey.trim();
    if (!key || key in triggers) {
      setNewKey("");
      return;
    }
    onChange({ ...triggers, [key]: [] });
    setNewKey("");
  };

  return (
    <div className="mt-2 space-y-2">
      {entries.length === 0 && (
        <div className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
          Sin triggers configurados.
        </div>
      )}
      {entries.map(([key, values]) => (
        <div key={key} className="rounded-md border p-2">
          <div className="flex items-center gap-2">
            <Input
              defaultValue={key}
              onBlur={(e) => updateKey(key, e.target.value)}
              className="font-mono text-xs"
              placeholder="!nombre_workflow"
            />
            <Button variant="ghost" size="icon" onClick={() => remove(key)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="mt-2">
            <ChipInput
              values={values}
              onChange={(next) => updateValues(key, next)}
              placeholder="frases que activan este workflow…"
            />
          </div>
        </div>
      ))}
      <div className="flex items-center gap-2">
        <Input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="!nuevo_trigger"
          className="font-mono text-xs"
        />
        <Button variant="outline" size="sm" onClick={add}>
          <Plus className="mr-1 h-3.5 w-3.5" /> Agregar
        </Button>
      </div>
    </div>
  );
}

function KnowledgeTab({
  config,
  onChange,
}: {
  config: KnowledgeConfig;
  onChange: (next: Partial<KnowledgeConfig>) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Controla qué fuentes de conocimiento puede consultar este agente cuando el cliente pregunta algo.
      </p>
      <ToggleRow
        label="Modo estricto"
        description="Sólo responde con información encontrada en las fuentes de conocimiento. Si no hay match, escala."
        checked={config.strict_ks}
        onChange={(v) => onChange({ strict_ks: v })}
      />
      <ToggleRow
        label="Catálogo / fuentes estructuradas"
        description="Tablas con modelos, precios y especificaciones."
        checked={config.structured_enabled}
        onChange={(v) => onChange({ structured_enabled: v })}
      />
      <ToggleRow
        label="Artículos y FAQ"
        description="Documentación semi-estructurada del KB."
        checked={config.semi_structured_enabled}
        onChange={(v) => onChange({ semi_structured_enabled: v })}
      />
      <ToggleRow
        label="Documentos libres (PDF, web)"
        description="Documentos indexados con embeddings."
        checked={config.free_text_enabled}
        onChange={(v) => onChange({ free_text_enabled: v })}
      />
    </div>
  );
}

function MemoryTab({
  rules,
  onChange,
}: {
  rules: MemoryRules;
  onChange: (next: Partial<MemoryRules>) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Configura cómo el agente recuerda turnos previos y aprende de las conversaciones reales.
      </p>
      <ToggleRow
        label="Memoria conversacional"
        description="Mantiene el contexto de los turnos previos para no repetir información."
        checked={rules.enabled}
        onChange={(v) => onChange({ enabled: v })}
      />
      <div>
        <Label>Mensajes recientes a recordar</Label>
        <Input
          type="number"
          min={5}
          max={100}
          value={rules.max_history_messages}
          onChange={(e) => onChange({ max_history_messages: Number(e.target.value || 20) })}
          className="mt-1 max-w-[160px]"
        />
        <p className="mt-1 text-[11px] text-muted-foreground">
          Más historial = mejor contexto pero mayor costo por respuesta.
        </p>
      </div>
      <ToggleRow
        label="Aprender de clientes"
        description="Detecta patrones en las preguntas reales para sugerir mejoras al KB."
        checked={rules.learn_from_customers}
        onChange={(v) => onChange({ learn_from_customers: v })}
      />
      <ToggleRow
        label="Aprender de operadores humanos"
        description="Aprende de las correcciones y respuestas que escriben los operadores."
        checked={rules.learn_from_human_feedback}
        onChange={(v) => onChange({ learn_from_human_feedback: v })}
      />
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 rounded-md border p-3 hover:bg-muted/40">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5"
      />
      <div className="flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{description}</div>
      </div>
    </label>
  );
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  meta?: string;
}

function TestTab({ agent }: { agent: AgentItem }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Escribe una pregunta y probaré este agente con la configuración actual, sin afectar conversaciones reales.",
    },
  ]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const test = useMutation({
    mutationFn: (text: string) =>
      agentsApi.test(agent as unknown as Record<string, unknown>, text),
    onSuccess: (res) => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.response,
          meta: `Intent: ${res.intent} · modo: ${res.flow_mode}`,
        },
      ]);
    },
    onError: (e) => toast.error("Error en la prueba", { description: e.message }),
  });

  const send = () => {
    const text = input.trim();
    if (!text || test.isPending) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    test.mutate(text);
  };

  return (
    <div className="flex h-[480px] flex-col gap-3 rounded-md border">
      <div ref={scrollRef} className="flex-1 space-y-2 overflow-y-auto p-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                m.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-foreground"
              }`}
            >
              <div>{m.content}</div>
              {m.meta && (
                <div className="mt-1 text-[10px] uppercase tracking-wide opacity-70">{m.meta}</div>
              )}
            </div>
          </div>
        ))}
        {test.isPending && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> pensando…
            </div>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 border-t p-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Escribe un mensaje de prueba…"
          disabled={test.isPending}
        />
        <Button onClick={send} disabled={test.isPending || !input.trim()}>
          <Send className="mr-1 h-3.5 w-3.5" /> Enviar
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setMessages([{ role: "assistant", content: "Conversación reiniciada." }])}
          title="Reiniciar"
        >
          <Play className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

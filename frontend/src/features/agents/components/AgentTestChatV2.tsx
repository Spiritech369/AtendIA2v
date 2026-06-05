import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Braces,
  FileText,
  Loader2,
  MessageCircle,
  Play,
  ShieldCheck,
  User,
} from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  type AgentItem,
  type AgentTestTurnContactField,
  type AgentTestTurnHistoryItem,
  type AgentTestTurnV2Response,
  agentsApi,
} from "@/features/agents/api";
import { cn } from "@/lib/utils";

type ChatEntry =
  | { id: string; role: "customer"; text: string }
  | { id: string; role: "agent"; text: string; result: AgentTestTurnV2Response };

const DEFAULT_CONTACT_FIELDS = JSON.stringify(
  [
    { key: "email", label: "Email", field_type: "text" },
    { key: "priority", label: "Priority", field_type: "text" },
  ],
  null,
  2,
);

export function AgentTestChatV2({ agent }: { agent: AgentItem }) {
  const [message, setMessage] = useState("");
  const [lifecycleStage, setLifecycleStage] = useState("");
  const [sourceIds, setSourceIds] = useState("");
  const [contactFieldsJson, setContactFieldsJson] = useState(DEFAULT_CONTACT_FIELDS);
  const [saveReadiness, setSaveReadiness] = useState(false);
  const [requiresCitation, setRequiresCitation] = useState(false);
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const [lastResult, setLastResult] = useState<AgentTestTurnV2Response | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const conversationHistory = useMemo<AgentTestTurnHistoryItem[]>(
    () =>
      history.map((item) => ({
        role: item.role === "customer" ? "customer" : "agent",
        text: item.text,
      })),
    [history],
  );

  const mutation = useMutation({
    mutationFn: async () => {
      const trimmed = message.trim();
      if (!trimmed) throw new Error("Escribe un mensaje de prueba.");
      return agentsApi.testTurnV2(agent.id, {
        test_message: trimmed,
        conversation_history: conversationHistory,
        contact_fields: parseContactFields(contactFieldsJson),
        lifecycle_stage: lifecycleStage.trim() || null,
        knowledge_source_ids: parseSourceIds(sourceIds),
        save_readiness_evidence: saveReadiness,
        requires_knowledge_citation: requiresCitation,
        metadata: { surface: "agent_test_chat_v2", dry_run: true },
      });
    },
    onSuccess: (result) => {
      const customerText = message.trim();
      setHistory((current) => [
        ...current,
        { id: newId(), role: "customer", text: customerText },
        {
          id: newId(),
          role: "agent",
          text: result.final_message,
          result,
        },
      ]);
      setLastResult(result);
      setMessage("");
      setLocalError(null);
    },
    onError: (error) => {
      setLocalError(errorMessage(error));
    },
  });

  const submit = () => {
    if (mutation.isPending) return;
    mutation.mutate();
  };

  const detailResult = lastResult ?? lastAgentResult(history);
  const confidence = Math.round((detailResult?.confidence ?? 0) * 100);

  return (
    <section className="rounded-lg border border-sky-300/20 bg-slate-950/80">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Bot className="h-4 w-4 text-sky-300" />
          <div>
            <div className="text-sm font-semibold text-slate-100">Agent Test Chat v2</div>
            <div className="text-[11px] text-slate-500">Test mode / Dry run</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="border-emerald-300/30 bg-emerald-500/10 text-emerald-200"
          >
            No persistence
          </Badge>
          <Badge variant="outline" className="border-sky-300/30 bg-sky-500/10 text-sky-200">
            Confidence {confidence}%
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 p-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
        <div className="min-w-0 space-y-3">
          <div className="min-h-64 space-y-2 rounded-lg border border-white/10 bg-black/20 p-3">
            {history.length === 0 ? (
              <div className="grid min-h-56 place-items-center text-center text-xs text-slate-500">
                <div>
                  <MessageCircle className="mx-auto mb-2 h-7 w-7 text-slate-600" />
                  Envia un mensaje de prueba para ver la respuesta del runtime v2.
                </div>
              </div>
            ) : (
              history.map((item) => (
                <div
                  key={item.id}
                  className={cn("flex", item.role === "customer" ? "justify-end" : "justify-start")}
                >
                  <div
                    className={cn(
                      "max-w-[86%] rounded-lg px-3 py-2 text-sm leading-relaxed shadow whitespace-pre-wrap",
                      item.role === "customer"
                        ? "rounded-tr-sm bg-slate-700 text-white"
                        : "rounded-tl-sm bg-emerald-700 text-white",
                    )}
                  >
                    <div className="mb-1 flex items-center gap-1 text-[10px] opacity-75">
                      {item.role === "customer" ? (
                        <User className="h-3 w-3" />
                      ) : (
                        <Bot className="h-3 w-3" />
                      )}
                      {item.role === "customer" ? "Cliente" : "Agente"}
                    </div>
                    {item.text}
                  </div>
                </div>
              ))
            )}
          </div>

          {localError ? (
            <div className="rounded-md border border-red-300/30 bg-red-500/10 px-3 py-2 text-xs text-red-100">
              <div className="flex items-center gap-2 font-semibold">
                <AlertTriangle className="h-3.5 w-3.5" />
                Policy/debug error
              </div>
              <div className="mt-1 whitespace-pre-wrap text-red-100/90">{localError}</div>
            </div>
          ) : null}

          <div className="space-y-2">
            <Textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  submit();
                }
              }}
              placeholder="Escribe el mensaje del cliente..."
              className="min-h-24 border-white/10 bg-black/20 text-sm text-slate-100"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[11px] text-slate-500">Ctrl/Cmd + Enter para enviar</div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 border-white/10 bg-white/[0.035] text-xs text-slate-200"
                  onClick={() => {
                    setHistory([]);
                    setLastResult(null);
                    setLocalError(null);
                  }}
                >
                  Limpiar
                </Button>
                <Button
                  type="button"
                  onClick={submit}
                  disabled={mutation.isPending || !message.trim()}
                  className="h-8 bg-sky-600 text-xs hover:bg-sky-500"
                >
                  {mutation.isPending ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Run test
                </Button>
              </div>
            </div>
          </div>
        </div>

        <aside className="min-w-0 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label
              htmlFor="agent-test-lifecycle-stage"
              className="space-y-1 text-[11px] text-slate-400"
            >
              Lifecycle simulado
              <Input
                id="agent-test-lifecycle-stage"
                value={lifecycleStage}
                onChange={(event) => setLifecycleStage(event.target.value)}
                placeholder="new"
                className="h-8 border-white/10 bg-black/20 text-xs text-slate-100"
              />
            </label>
            <label htmlFor="agent-test-source-ids" className="space-y-1 text-[11px] text-slate-400">
              Knowledge source IDs
              <Input
                id="agent-test-source-ids"
                value={sourceIds}
                onChange={(event) => setSourceIds(event.target.value)}
                placeholder="uuid, uuid"
                className="h-8 border-white/10 bg-black/20 text-xs text-slate-100"
              />
            </label>
          </div>
          <label
            htmlFor="agent-test-contact-fields"
            className="block space-y-1 text-[11px] text-slate-400"
          >
            Contact fields visibles
            <Textarea
              id="agent-test-contact-fields"
              value={contactFieldsJson}
              onChange={(event) => setContactFieldsJson(event.target.value)}
              className="min-h-24 border-white/10 bg-black/20 font-mono text-[11px] text-slate-100"
            />
          </label>
          <div className="grid gap-2 rounded-lg border border-white/10 bg-white/[0.035] p-2 text-xs text-slate-300">
            <label className="flex items-center justify-between gap-3">
              <span>Save readiness evidence</span>
              <input
                type="checkbox"
                checked={saveReadiness}
                onChange={(event) => setSaveReadiness(event.target.checked)}
                className="h-4 w-4"
              />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span>Requires citation</span>
              <input
                type="checkbox"
                checked={requiresCitation}
                onChange={(event) => setRequiresCitation(event.target.checked)}
                className="h-4 w-4"
              />
            </label>
          </div>

          <ResultSummary result={detailResult} />
        </aside>
      </div>
    </section>
  );
}

function ResultSummary({ result }: { result: AgentTestTurnV2Response | null }) {
  if (!result) {
    return (
      <div className="rounded-lg border border-white/10 bg-white/[0.035] p-3 text-xs text-slate-500">
        El panel mostrara fuentes, acciones, field updates y debug despues del primer turno.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2">
        <MiniMetric label="Confidence" value={`${Math.round(result.confidence * 100)}%`} />
        <MiniMetric label="Human" value={result.needs_human ? "yes" : "no"} />
        <MiniMetric label="Risks" value={String(result.risk_flags.length)} />
      </div>
      {result.risk_flags.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {result.risk_flags.map((flag) => (
            <Badge key={flag} variant="outline" className="border-amber-300/30 text-amber-200">
              {flag}
            </Badge>
          ))}
        </div>
      ) : null}
      <DetailBlock
        title="Source cards / citations"
        icon={<FileText className="h-3.5 w-3.5 text-sky-300" />}
        empty="Sin citations."
      >
        {result.knowledge_citations.length > 0
          ? result.knowledge_citations.map((citation) => (
              <div
                key={citation.source_id ?? citation.title ?? citation.snippet ?? "source"}
                className="rounded-md border border-white/10 bg-black/20 p-2"
              >
                <div className="text-xs font-medium text-slate-100">
                  {citation.title || citation.source_id || "Source"}
                </div>
                {citation.snippet ? (
                  <div className="mt-1 text-[11px] text-slate-400">{citation.snippet}</div>
                ) : null}
                {typeof citation.score === "number" ? (
                  <div className="mt-1 text-[10px] text-slate-500">
                    score {citation.score.toFixed(2)}
                  </div>
                ) : null}
              </div>
            ))
          : null}
      </DetailBlock>
      <JsonDetail title="Field updates" value={result.field_updates} />
      <JsonDetail title="Lifecycle update" value={result.lifecycle_update} />
      <JsonDetail title="Actions" value={result.actions} />
      <JsonDetail title="Policy / debug" value={result.debug} />
      <JsonDetail title="Trace metadata" value={result.trace_metadata} />
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.035] px-2 py-1.5">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function DetailBlock({
  title,
  icon,
  empty,
  children,
}: {
  title: string;
  icon: ReactNode;
  empty?: string;
  children: ReactNode;
}) {
  const hasChildren = Boolean(children);
  return (
    <details className="rounded-lg border border-white/10 bg-white/[0.035]" open>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-100">
        {icon}
        {title}
      </summary>
      <div className="space-y-2 border-t border-white/10 p-2">
        {hasChildren ? children : <div className="text-xs text-slate-500">{empty}</div>}
      </div>
    </details>
  );
}

function JsonDetail({ title, value }: { title: string; value: unknown }) {
  const isEmpty =
    value == null ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0);
  return (
    <details className="rounded-lg border border-white/10 bg-white/[0.035]">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-100">
        {title === "Policy / debug" ? (
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
        ) : (
          <Braces className="h-3.5 w-3.5 text-slate-300" />
        )}
        {title}
      </summary>
      <pre className="max-h-56 overflow-auto border-t border-white/10 p-2 text-[11px] text-slate-300">
        {isEmpty ? "No data" : JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function parseContactFields(raw: string): AgentTestTurnContactField[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  const parsed = JSON.parse(trimmed);
  if (!Array.isArray(parsed)) throw new Error("Contact fields debe ser un arreglo JSON.");
  return parsed.map((item) => {
    const record = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
    return {
      key: String(record.key || ""),
      label: String(record.label || record.key || ""),
      field_type: String(record.field_type || "text"),
      options:
        record.options && typeof record.options === "object"
          ? (record.options as Record<string, unknown>)
          : null,
    };
  });
}

function parseSourceIds(raw: string): string[] | null {
  const ids = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return ids.length > 0 ? ids : null;
}

function lastAgentResult(history: ChatEntry[]): AgentTestTurnV2Response | null {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const item = history[index];
    if (item?.role === "agent") return item.result;
  }
  return null;
}

function errorMessage(error: unknown): string {
  const data = (error as { response?: { data?: { detail?: unknown } }; message?: string }).response
    ?.data;
  const detail = data?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const record = detail as {
      message?: string;
      issues?: Array<{ code?: string; message?: string }>;
    };
    const issues = Array.isArray(record.issues)
      ? record.issues
          .map((issue) => `${issue.code ? `${issue.code}: ` : ""}${issue.message ?? ""}`)
          .filter(Boolean)
          .join("\n")
      : "";
    return [record.message, issues].filter(Boolean).join("\n");
  }
  if (typeof detail === "string") return detail;
  if (error instanceof Error) return error.message;
  return "No se pudo ejecutar el test turn.";
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

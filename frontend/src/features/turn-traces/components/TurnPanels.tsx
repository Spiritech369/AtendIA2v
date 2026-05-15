// Secondary panels rendered below the story in DebugPanel /
// TurnTraceInspector. Each one is self-contained, vertical-agnostic
// (no hardcoded field names), and degrades cleanly when its data is
// missing from the trace.

import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Bot,
  CheckCircle2,
  Circle,
  CircleAlert,
  Clock,
  DollarSign,
  Gavel,
  Plus,
  Sparkles,
  Zap,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { TurnTraceDetail } from "@/features/turn-traces/api";
import {
  type Anomaly,
  analyzeActions,
  analyzeLatencyPerStep,
  analyzePromptTemplate,
  type ClassifiedEntity,
  type CostSlice,
  classifyEntities,
  costSlices,
  detectAnomalies,
  diffState,
  extractKnowledge,
  type KnowledgeHit,
  readFactPack,
  type StateChange,
} from "@/features/turn-traces/lib/turnAnalysis";
import { cn } from "@/lib/utils";

function formatScalar(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v.length > 60 ? `${v.slice(0, 60)}…` : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    const s = JSON.stringify(v);
    return s.length > 60 ? `${s.slice(0, 60)}…` : s;
  } catch {
    return String(v);
  }
}

function PanelHeader({
  icon: Icon,
  title,
  count,
}: {
  icon: React.ElementType;
  title: string;
  count?: number;
}) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
      <Icon className="h-3 w-3" />
      <span>{title}</span>
      {count != null && <span className="text-muted-foreground/60">·</span>}
      {count != null && <span className="text-foreground/80">{count}</span>}
    </div>
  );
}

// ── Anomaly chips (rendered in the header above the story) ──────────

const ANOMALY_CLASSES: Record<Anomaly["kind"], string> = {
  slow: "bg-amber-500/15 text-amber-700 border-amber-500/40",
  low_confidence: "bg-amber-500/15 text-amber-700 border-amber-500/40",
  errors: "bg-rose-500/15 text-rose-700 border-rose-500/40",
  no_composer: "bg-rose-500/15 text-rose-700 border-rose-500/40",
  bot_paused: "bg-slate-500/15 text-slate-700 border-slate-500/40",
};

export function AnomalyChips({ trace }: { trace: TurnTraceDetail }) {
  const anomalies = detectAnomalies(trace);
  if (anomalies.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {anomalies.map((a) => (
        <Badge
          key={`${a.kind}-${a.label}`}
          variant="outline"
          className={cn("text-[10px] font-medium", ANOMALY_CLASSES[a.kind])}
          title={a.detail}
        >
          {a.label}
        </Badge>
      ))}
    </div>
  );
}

// ── Entity pills ────────────────────────────────────────────────────

const STATUS_LABELS: Record<
  ClassifiedEntity["status"],
  { label: string; classes: string; Icon: React.ElementType }
> = {
  extracted_saved: {
    label: "Guardado este turno",
    classes: "bg-emerald-500/15 text-emerald-700 border-emerald-500/40",
    Icon: Plus,
  },
  extracted_not_saved: {
    label: "Detectado pero NO guardado",
    classes: "bg-amber-500/15 text-amber-700 border-amber-500/40",
    Icon: CircleAlert,
  },
  previously_saved: {
    label: "De turnos anteriores",
    classes: "bg-slate-500/10 text-slate-600 border-slate-500/30",
    Icon: Circle,
  },
};

export function EntityPills({ trace }: { trace: TurnTraceDetail }) {
  const entities = classifyEntities(trace);

  if (entities.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={Sparkles} title="Entidades" />
        <div className="text-xs text-muted-foreground">No se extrajeron entidades este turno.</div>
      </div>
    );
  }

  const groups: Record<ClassifiedEntity["status"], ClassifiedEntity[]> = {
    extracted_saved: [],
    extracted_not_saved: [],
    previously_saved: [],
  };
  for (const e of entities) groups[e.status].push(e);

  return (
    <div className="space-y-2">
      <PanelHeader icon={Sparkles} title="Entidades" count={entities.length} />
      <div className="space-y-2">
        {(Object.keys(groups) as ClassifiedEntity["status"][]).map((status) => {
          const list = groups[status];
          if (list.length === 0) return null;
          const meta = STATUS_LABELS[status];
          return (
            <div key={status} className="space-y-1">
              <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                <meta.Icon className="h-3 w-3" />
                {meta.label}
              </div>
              <div className="flex flex-wrap gap-1">
                {list.map((e) => (
                  <Badge
                    key={`${status}-${e.field}`}
                    variant="outline"
                    className={cn("font-mono text-[10px]", meta.classes)}
                    title={e.sourceTurn != null ? `turno ${e.sourceTurn}` : undefined}
                  >
                    <span className="font-medium">{e.field}</span>
                    <span className="mx-1 text-muted-foreground/60">=</span>
                    <span>{formatScalar(e.value)}</span>
                  </Badge>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Knowledge panel ─────────────────────────────────────────────────

const SOURCE_LABELS: Record<KnowledgeHit["source"], string> = {
  faq: "FAQ",
  catalog: "Catálogo",
  quote: "Cotización",
};

function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  const tone = score >= 0.75 ? "bg-emerald-500" : score >= 0.55 ? "bg-amber-500" : "bg-slate-400";
  return (
    <div className="flex items-center gap-1.5">
      <div className="relative h-1.5 w-16 overflow-hidden rounded bg-muted">
        <div className={cn("absolute inset-y-0 left-0", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[10px] text-muted-foreground">{score.toFixed(2)}</span>
    </div>
  );
}

export function KnowledgePanel({ trace }: { trace: TurnTraceDetail }) {
  const kb = extractKnowledge(trace);

  if (kb.hits.length === 0 && !kb.emptyHint && !kb.action) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={BookOpen} title="Conocimiento usado" />
        <div className="text-xs text-muted-foreground">
          No se consultó la base de conocimiento en este turno.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <PanelHeader
        icon={BookOpen}
        title="Conocimiento usado"
        count={kb.hits.length > 0 ? kb.hits.length : undefined}
      />
      {kb.action && kb.hits.length === 0 && (
        <div className="text-xs text-muted-foreground">
          Acción <span className="font-mono">{kb.action}</span>
          {kb.emptyHint ? ` — ${kb.emptyHint}` : " — sin resultados."}
        </div>
      )}
      {kb.hits.length > 0 && (
        <div className="space-y-1.5">
          {kb.hits.map((h, idx) => (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: hits derive from immutable action_payload.
              key={`${h.source}-${idx}-${h.externalId ?? h.title.slice(0, 16)}`}
              className="rounded-md border bg-card p-2"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    {SOURCE_LABELS[h.source]}
                  </Badge>
                  <span className="truncate text-xs font-medium">{h.title}</span>
                </div>
                {h.score != null && <ScoreBar score={h.score} />}
              </div>
              {h.preview && (
                <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                  {h.preview}
                </div>
              )}
              {h.externalId && (
                <div className="mt-1 font-mono text-[10px] text-muted-foreground/70">
                  id: {h.externalId}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Actions panel (composer_output.action_payload) ──────────────────

export function ActionsPanel({ trace }: { trace: TurnTraceDetail }) {
  const actions = analyzeActions(trace);
  if (actions.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={Zap} title="Acciones" />
        <div className="text-xs text-muted-foreground">Sin acciones disparadas este turno.</div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <PanelHeader icon={Zap} title="Acciones" count={actions.length} />
      <div className="space-y-1">
        {actions.map((a) => (
          <details key={a.name} className="rounded-md border bg-card text-xs">
            <summary className="cursor-pointer px-2 py-1.5">
              <span className="font-mono font-medium">{a.name}</span>
              <span className="ml-2 text-muted-foreground">· {a.preview}</span>
            </summary>
            <pre className="max-h-32 overflow-auto border-t bg-muted/30 p-2 text-[10px]">
              {JSON.stringify(a.raw, null, 2)}
            </pre>
          </details>
        ))}
      </div>
    </div>
  );
}

// ── State diff (git-style) ──────────────────────────────────────────

const KIND_LABELS: Record<StateChange["kind"], { label: string; classes: string }> = {
  added: { label: "+", classes: "text-emerald-600" },
  removed: { label: "−", classes: "text-rose-600" },
  changed: { label: "~", classes: "text-amber-600" },
  stage: { label: "→", classes: "text-violet-600" },
};

export function StateDiff({ trace }: { trace: TurnTraceDetail }) {
  const changes = diffState(trace);

  if (changes.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={ArrowRight} title="Cambios de estado" />
        <div className="text-xs text-muted-foreground">Sin cambios este turno.</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <PanelHeader icon={ArrowRight} title="Cambios de estado" count={changes.length} />
      <div className="space-y-1">
        {changes.map((c, idx) => {
          const meta = KIND_LABELS[c.kind];
          return (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: diff order is stable per render.
              key={`${idx}-${c.field}`}
              className="flex items-start gap-2 text-xs"
            >
              <span
                className={cn("w-3 shrink-0 text-center font-mono font-semibold", meta.classes)}
              >
                {meta.label}
              </span>
              <span className="w-32 shrink-0 truncate font-mono text-muted-foreground">
                {c.field}
              </span>
              <div className="flex min-w-0 flex-1 items-center gap-1">
                {c.kind !== "added" && (
                  <span className="truncate text-muted-foreground/80 line-through">
                    {formatScalar(c.before)}
                  </span>
                )}
                {c.kind === "changed" && (
                  <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                )}
                {c.kind !== "removed" && (
                  <span className="truncate font-medium">{formatScalar(c.after)}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Latency per-step breakdown ──────────────────────────────────────
// Task 10 / item 4 — replaces the old single-bar LatencyStackedBar
// with a per-step view (NLU · Vision · Composer · Tools · Overhead).
// Each row gets its own mini-bar so operators can spot whether the
// turn was slow because of NLU, composer streaming, a slow tool call,
// or unaccounted overhead.

export function LatencyPerStepBar({ trace }: { trace: TurnTraceDetail }) {
  const slices = analyzeLatencyPerStep(trace);
  const total = trace.total_latency_ms ?? 0;
  if (slices.length === 0) return null;
  return (
    <div className="space-y-2">
      <PanelHeader icon={Clock} title={`Latencia · ${total}ms`} />
      <div className="space-y-1">
        {slices.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-[11px]">
            <span className="w-20 text-muted-foreground">{s.label}</span>
            <div className="relative h-2 flex-1 overflow-hidden rounded bg-muted">
              <div
                className="absolute inset-y-0 left-0 bg-primary/60"
                style={{ width: `${s.pct}%` }}
              />
            </div>
            <span className="w-16 text-right font-mono text-muted-foreground">{s.ms}ms</span>
            <span className="w-10 text-right font-mono text-muted-foreground">{s.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Backwards-compat alias — DebugPanel still imports the old name.
export const LatencyStackedBar = LatencyPerStepBar;

// ── Cost breakdown ──────────────────────────────────────────────────

export function CostBreakdown({ trace }: { trace: TurnTraceDetail }) {
  const { slices, totalUsd } = costSlices(trace);

  if (totalUsd === 0 && slices.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={DollarSign} title="Costo" />
        <div className="text-xs text-muted-foreground">$0.00 este turno.</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <PanelHeader icon={DollarSign} title="Costo" />
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        {slices.map((s: CostSlice) => (
          <div key={s.label} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-sm", s.classes)} />
            <span className="text-muted-foreground">{s.label}</span>
            <span className="ml-auto font-mono text-foreground/80">${s.usd.toFixed(4)}</span>
          </div>
        ))}
      </div>
      <div className="text-right text-[10px] text-muted-foreground">
        Total ${totalUsd.toFixed(4)}
      </div>
    </div>
  );
}

// ── Error banner (rendered at top when present) ─────────────────────

export function ErrorBanner({ trace }: { trace: TurnTraceDetail }) {
  const errors = trace.errors ?? [];
  if (errors.length === 0) return null;

  return (
    <div className="space-y-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 p-2.5">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700">
        <AlertTriangle className="h-3.5 w-3.5" />
        Errores en este turno
      </div>
      <ul className="space-y-1">
        {errors.map((err, i) => {
          const serialized = typeof err === "string" ? err : JSON.stringify(err);
          return (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: errors come from immutable trace JSON.
              key={`${i}-${serialized.slice(0, 24)}`}
              className="rounded bg-rose-500/10 p-1.5 text-[11px] text-rose-800"
            >
              {serialized}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── Fact pack (what the composer actually saw) ──────────────────────

export function FactPackCard({ trace }: { trace: TurnTraceDetail }) {
  const fp = readFactPack(trace);
  const brandKeys = Object.keys(fp.brandFacts);
  const extractedKeys = Object.keys(fp.extractedData);
  const hasAnything =
    brandKeys.length > 0 ||
    extractedKeys.length > 0 ||
    fp.visionResult != null ||
    (fp.actionPayload && Object.keys(fp.actionPayload).length > 0);

  if (!hasAnything) return null;

  return (
    <div className="space-y-2">
      <PanelHeader icon={CheckCircle2} title="Contexto que vio el bot" />
      <details className="rounded-md border bg-card text-xs">
        <summary className="cursor-pointer px-2 py-1.5 text-muted-foreground hover:text-foreground">
          Ver detalle ({brandKeys.length} brand facts · {extractedKeys.length} campos
          {fp.visionResult ? " · vision" : ""})
        </summary>
        <pre className="max-h-48 overflow-auto border-t bg-muted/30 p-2 text-[10px]">
          {JSON.stringify(
            {
              brand_facts: fp.brandFacts,
              extracted_data: fp.extractedData,
              vision_result: fp.visionResult,
              action_payload: fp.actionPayload,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </div>
  );
}

// ── Rules evaluated (Migration 045) ─────────────────────────────────

export function RulesEvaluatedPanel({ trace }: { trace: TurnTraceDetail }) {
  const rules = trace.rules_evaluated;
  if (!rules) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={Gavel} title="Reglas evaluadas" />
        <div className="text-xs text-muted-foreground">
          No se evaluaron reglas de pipeline este turno.
        </div>
      </div>
    );
  }
  if (rules.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={Gavel} title="Reglas evaluadas" />
        <div className="text-xs text-muted-foreground">Sin reglas configuradas en el pipeline.</div>
      </div>
    );
  }

  // Group by stage so the operator sees "stage X had rules Y, Z; stage W
  // had rule V" — clearer than a flat 30-row list.
  const byStage = new Map<string, typeof rules>();
  for (const r of rules) {
    const arr = byStage.get(r.stage_id) ?? [];
    arr.push(r);
    byStage.set(r.stage_id, arr);
  }

  return (
    <div className="space-y-2">
      <PanelHeader icon={Gavel} title="Reglas evaluadas" count={rules.length} />
      <div className="space-y-2">
        {Array.from(byStage.entries()).map(([stageId, stageRules]) => (
          <div key={stageId} className="space-y-1 rounded-md border bg-card p-2">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-mono font-medium">{stageId}</span>
              <span className="text-muted-foreground">
                {stageRules.filter((r) => r.passed).length}/{stageRules.length} pass
              </span>
            </div>
            <ul className="space-y-0.5">
              {stageRules.map((r) => (
                <li
                  key={`${r.stage_id}-${r.condition_index}`}
                  className="flex items-center gap-2 text-[11px]"
                >
                  <span
                    className={cn(
                      "w-3 shrink-0 text-center font-mono font-semibold",
                      r.passed ? "text-emerald-600" : "text-rose-600",
                    )}
                  >
                    {r.passed ? "✓" : "×"}
                  </span>
                  <span className="font-mono text-muted-foreground">{r.field}</span>
                  <span className="text-muted-foreground/70">{r.operator}</span>
                  {r.value != null && (
                    <span className="truncate font-mono text-foreground/80">
                      {formatScalar(r.value)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Agent badge (Migration 045 + A15 deep link) ─────────────────────

export function AgentBadge({ trace }: { trace: TurnTraceDetail }) {
  if (!trace.agent_id) return null;
  // A15 — deep link to the agent editor for the agent that handled
  // this turn. Operator clicks the chip → lands in /agents/$id with
  // the right row preselected so they can inspect prompt/guardrails/KB
  // filter without having to navigate the agents page manually.
  return (
    <Link
      to="/agents/$agentId"
      params={{ agentId: trace.agent_id }}
      className="inline-block"
      title={`Ver agente ${trace.agent_id}`}
    >
      <Badge
        variant="outline"
        className="border-violet-500/40 bg-violet-500/10 text-violet-700 text-[10px] font-mono hover:bg-violet-500/20 transition-colors"
      >
        <Bot className="mr-1 h-3 w-3" />
        Agente {trace.agent_id.slice(0, 8)}
      </Badge>
    </Link>
  );
}

// ── Prompt template breakdown (Task 11 / item 7) ────────────────────
// Parses the assembled system prompt by `### SECTION` markers and
// renders one mini-bar per section showing estimated tokens (chars/4)
// and % of the total prompt. Helps operators spot prompts that are
// bottom-heavy on knowledge or top-heavy on guardrails — visual cue
// for where the token budget actually goes.

export function PromptTemplateBreakdown({ trace }: { trace: TurnTraceDetail }) {
  const sections = analyzePromptTemplate(trace);
  if (sections.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={BookOpen} title="Anatomía del prompt" />
        <div className="text-xs text-muted-foreground">Sin prompt analizable.</div>
      </div>
    );
  }
  const totalTokens = sections.reduce((a, s) => a + s.tokens, 0);
  return (
    <div className="space-y-2">
      <PanelHeader icon={BookOpen} title={`Anatomía del prompt · ~${totalTokens} tokens`} />
      <div className="space-y-1">
        {sections.map((s) => (
          <div key={s.title} className="flex items-center gap-2 text-[11px]">
            <span className="w-32 truncate text-muted-foreground">{s.title}</span>
            <div className="relative h-2 flex-1 overflow-hidden rounded bg-muted">
              <div
                className="absolute inset-y-0 left-0 bg-violet-500/60"
                style={{ width: `${s.pct}%` }}
              />
            </div>
            <span className="w-12 text-right font-mono text-muted-foreground">{s.tokens}t</span>
            <span className="w-10 text-right font-mono text-muted-foreground">{s.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Raw JSON footer ─────────────────────────────────────────────────

export function RawJsonFooter({ trace }: { trace: TurnTraceDetail }) {
  return (
    <details className="rounded-md border bg-card text-xs">
      <summary className="cursor-pointer px-2 py-1.5 text-muted-foreground hover:text-foreground">
        Raw JSON del turno
      </summary>
      <pre className="max-h-80 overflow-auto border-t bg-muted/30 p-2 text-[10px]">
        {JSON.stringify(trace, null, 2)}
      </pre>
    </details>
  );
}

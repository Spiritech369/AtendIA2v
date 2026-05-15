// The story is the top section of the DebugPanel: a vertical timeline
// of what happened in the turn, top-down. Each step is a card with an
// icon, primary line, and optional secondary content (intent bar, KB
// hits, outbound messages, etc.).
//
// Vertical-agnostic: no step looks at field names or hardcoded
// vocabulary. The trace itself supplies labels.
import {
  ArrowRight,
  BookOpen,
  Brain,
  MessageSquareText,
  Paperclip,
  SendHorizonal,
  Target,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { StoryStep } from "../lib/turnStory";
import { FlowModeBadge } from "./FlowModeBadge";

// Human-readable intent labels. Keep `unclear` → "No claro" style. New
// intents fall back to their key (e.g. `complain` → `complain`), which
// is fine for now. When migration 021 lands with `agent_id`, this map
// moves to backend-provided labels.
const INTENT_LABELS: Record<string, string> = {
  greeting: "Saludo",
  ask_info: "Pidió información",
  ask_price: "Pidió precio",
  buy: "Quiere comprar",
  schedule: "Quiere agendar",
  complain: "Se quejó",
  off_topic: "Fuera de tema",
  unclear: "No claro",
};

function intentLabel(intent: string | null): string {
  if (!intent) return "—";
  return INTENT_LABELS[intent] ?? intent.replace(/_/g, " ");
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function StepShell({
  index,
  icon: Icon,
  primary,
  children,
}: {
  index: number;
  icon: React.ElementType;
  primary: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <li className="relative flex gap-3 py-2.5">
      <div className="flex flex-col items-center">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-card text-muted-foreground">
          <Icon className="h-3 w-3" />
        </div>
        <div className="mt-1 flex-1 w-px bg-border last:hidden" />
      </div>
      <div className="flex-1 space-y-1">
        <div className="flex items-baseline gap-2">
          <span className="text-[10px] font-mono text-muted-foreground">{`#${index + 1}`}</span>
          <div className="flex-1 text-sm">{primary}</div>
        </div>
        {children && <div className="space-y-1.5">{children}</div>}
      </div>
    </li>
  );
}

function IntentBar({ confidence }: { confidence: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(confidence * 100)));
  const tone =
    confidence >= 0.8 ? "bg-emerald-500" : confidence >= 0.6 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1.5 w-24 overflow-hidden rounded bg-muted">
        <div className={cn("absolute inset-y-0 left-0", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[10px] text-muted-foreground">{pct}%</span>
    </div>
  );
}

function StepInbound({
  index,
  step,
}: {
  index: number;
  step: Extract<StoryStep, { kind: "inbound" }>;
}) {
  // The body content (text bubble / media note / empty) is preserved as
  // a separate node so we can put the history-count chip on the right of
  // the primary header line without crowding the inbound text.
  const body = step.text ? (
    <>
      <span className="text-muted-foreground">Cliente escribió</span>
      <div className="mt-1 rounded-md bg-muted px-2 py-1.5 text-sm italic">«{step.text}»</div>
    </>
  ) : step.hasMedia ? (
    <span className="text-muted-foreground">Cliente envió un adjunto (sin texto).</span>
  ) : (
    <span className="text-muted-foreground">Sin mensaje entrante.</span>
  );

  return (
    <StepShell
      index={index}
      icon={step.hasMedia ? Paperclip : MessageSquareText}
      primary={
        step.totalTurns != null ? (
          <span className="flex w-full items-start justify-between gap-2">
            <span className="min-w-0 flex-1">{body}</span>
            <Badge
              variant="outline"
              className="shrink-0 font-mono text-[10px] text-muted-foreground"
              title={`turno ${step.turnNumber} de ${step.totalTurns}`}
            >
              {step.turnNumber} / {step.totalTurns}
            </Badge>
          </span>
        ) : (
          body
        )
      }
    />
  );
}

function StepNlu({ index, step }: { index: number; step: Extract<StoryStep, { kind: "nlu" }> }) {
  return (
    <StepShell
      index={index}
      icon={Brain}
      primary={
        <span>
          <span className="text-muted-foreground">El bot entendió</span>{" "}
          <span className="font-medium">{intentLabel(step.intent)}</span>
        </span>
      }
    >
      <div className="flex flex-wrap items-center gap-3 text-[11px]">
        {step.confidence != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Confianza:</span>
            <IntentBar confidence={step.confidence} />
          </div>
        )}
        {step.entityCount > 0 && (
          <span className="text-muted-foreground">
            {step.entityCount} entidad{step.entityCount === 1 ? "" : "es"} extraída
            {step.entityCount === 1 ? "" : "s"}
          </span>
        )}
      </div>
    </StepShell>
  );
}

function StepMode({ index, step }: { index: number; step: Extract<StoryStep, { kind: "mode" }> }) {
  return (
    <StepShell
      index={index}
      icon={Target}
      primary={
        <span className="flex items-center gap-1.5">
          <span className="text-muted-foreground">Router eligió modo</span>
          <FlowModeBadge mode={step.mode} />
        </span>
      }
    >
      {step.rationale && (
        <div className="text-[11px] text-muted-foreground">Porque: {step.rationale}</div>
      )}
    </StepShell>
  );
}

function StepKnowledge({
  index,
  step,
}: {
  index: number;
  step: Extract<StoryStep, { kind: "knowledge" }>;
}) {
  const hasHits = step.hits.length > 0;
  return (
    <StepShell
      index={index}
      icon={BookOpen}
      primary={
        <span>
          <span className="text-muted-foreground">Conocimiento consultado</span>
          {step.action && (
            <span className="ml-1.5 font-mono text-[11px] text-foreground/70">({step.action})</span>
          )}
        </span>
      }
    >
      {hasHits ? (
        <div className="space-y-1">
          {step.hits.slice(0, 3).map((h, i) => (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: ordered, immutable hits.
              key={`${i}-${h.title.slice(0, 12)}`}
              className="flex items-center justify-between gap-2 text-[11px]"
            >
              <span className="truncate">
                <span className="text-muted-foreground/70">·</span> {truncate(h.title, 60)}
              </span>
              {h.score != null && (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {h.score.toFixed(2)}
                </span>
              )}
            </div>
          ))}
          {step.hits.length > 3 && (
            <div className="text-[10px] text-muted-foreground">
              + {step.hits.length - 3} más en el panel de conocimiento
            </div>
          )}
        </div>
      ) : step.emptyHint ? (
        <div className="text-[11px] text-muted-foreground italic">{step.emptyHint}</div>
      ) : (
        <div className="text-[11px] text-muted-foreground italic">Sin resultados.</div>
      )}
    </StepShell>
  );
}

function StepComposer({
  index,
  step,
}: {
  index: number;
  step: Extract<StoryStep, { kind: "composer" }>;
}) {
  const hasMessages = step.messages.length > 0;
  return (
    <StepShell
      index={index}
      icon={SendHorizonal}
      primary={
        <span>
          <span className="text-muted-foreground">El bot respondió</span>
          {hasMessages && step.messages.length > 1 && (
            <span className="ml-1 text-muted-foreground">({step.messages.length} mensajes)</span>
          )}
        </span>
      }
    >
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
        {step.provider && (
          <Badge
            variant="outline"
            className={cn(
              "text-[10px]",
              step.provider === "openai" && "border-blue-500/40 bg-blue-500/10 text-blue-700",
              step.provider === "canned" && "border-amber-500/40 bg-amber-500/10 text-amber-700",
              step.provider === "fallback" && "border-rose-500/40 bg-rose-500/10 text-rose-700",
            )}
            title={`Composer adapter: ${step.provider}`}
          >
            {step.provider}
          </Badge>
        )}
        {step.model && <span className="font-mono">{step.model}</span>}
        {step.latencyMs != null && <span>· {step.latencyMs}ms</span>}
        {step.costUsd != null && step.costUsd > 0 && <span>· ${step.costUsd.toFixed(4)}</span>}
        {step.pendingConfirmation && (
          <Badge
            variant="outline"
            className="border-amber-500/40 bg-amber-500/10 text-amber-700 text-[10px]"
          >
            Pregunta sí/no: {step.pendingConfirmation}
          </Badge>
        )}
      </div>
      {hasMessages && (
        <div className="space-y-1">
          {step.messages.map((m, i) => (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: outbound messages are immutable per trace.
              key={`${i}-${m.slice(0, 16)}`}
              className="rounded-md bg-primary/5 px-2 py-1 text-[12px] text-foreground/90"
            >
              {truncate(m, 220)}
            </div>
          ))}
        </div>
      )}
      {step.rawLlmResponse && step.rawLlmResponse.length > 0 && (
        // Migration 045 — always surface the raw JSON when present.
        // The operator decides whether to expand; we don't second-guess
        // "is there a meaningful diff" because JSON wrapping bytes make
        // a byte-equal check meaningless.
        <details className="rounded-md border border-amber-500/40 bg-amber-500/5 text-[11px]">
          <summary className="cursor-pointer px-2 py-1 text-amber-700 hover:text-amber-900">
            Ver raw LLM
          </summary>
          <pre className="max-h-32 overflow-auto border-t border-amber-500/40 bg-amber-500/5 p-2 text-[10px] text-amber-900">
            {step.rawLlmResponse}
          </pre>
        </details>
      )}
    </StepShell>
  );
}

function StepTransition({
  index,
  step,
}: {
  index: number;
  step: Extract<StoryStep, { kind: "transition" }>;
}) {
  return (
    <StepShell
      index={index}
      icon={ArrowRight}
      primary={
        <span className="flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">Etapa:</span>
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{step.from}</code>
          <ArrowRight className="h-3 w-3 text-muted-foreground" />
          <code className="rounded bg-violet-500/15 px-1.5 py-0.5 font-mono text-[11px] text-violet-700">
            {step.to}
          </code>
        </span>
      }
    />
  );
}

export function TurnStoryView({ steps }: { steps: StoryStep[] }) {
  if (steps.length === 0) {
    return (
      <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
        Sin pasos para narrar este turno.
      </div>
    );
  }
  return (
    <ol className="relative space-y-0">
      {steps.map((step, idx) => {
        const key = `${step.kind}-${idx}`;
        switch (step.kind) {
          case "inbound":
            return <StepInbound key={key} index={idx} step={step} />;
          case "nlu":
            return <StepNlu key={key} index={idx} step={step} />;
          case "mode":
            return <StepMode key={key} index={idx} step={step} />;
          case "knowledge":
            return <StepKnowledge key={key} index={idx} step={step} />;
          case "composer":
            return <StepComposer key={key} index={idx} step={step} />;
          case "transition":
            return <StepTransition key={key} index={idx} step={step} />;
          default:
            return null;
        }
      })}
    </ol>
  );
}

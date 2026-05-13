import {
  ArrowRight,
  Brain,
  MessageSquareText,
  SendHorizonal,
  Sparkles,
  Target,
  Wrench,
} from "lucide-react";

import type { StoryStep } from "../lib/turnStory";
import { FlowModeBadge } from "./FlowModeBadge";

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

function StepRow({
  icon: Icon,
  children,
}: {
  icon: typeof MessageSquareText;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="flex-1 text-sm">{children}</div>
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function renderStep(step: StoryStep) {
  switch (step.kind) {
    case "inbound":
      return (
        <StepRow icon={MessageSquareText}>
          {step.text ? (
            <>
              <span className="text-muted-foreground">Cliente:</span>{" "}
              <span className="italic">«{step.text}»</span>
            </>
          ) : step.hasMedia ? (
            <span className="text-muted-foreground">Cliente envió un adjunto (sin texto).</span>
          ) : (
            <span className="text-muted-foreground">Sin mensaje entrante.</span>
          )}
        </StepRow>
      );
    case "nlu": {
      const entities = Object.entries(step.extracted ?? {});
      const intentLabel = step.intent ? (INTENT_LABELS[step.intent] ?? step.intent) : "—";
      return (
        <StepRow icon={Brain}>
          <span className="text-muted-foreground">Bot entendió:</span>{" "}
          <span className="font-medium">{intentLabel}</span>
          {entities.length > 0 && (
            <span className="ml-1 text-muted-foreground">
              ({entities.map(([k, v]) => `${k}=${String(v)}`).join(", ")})
            </span>
          )}
        </StepRow>
      );
    }
    case "mode":
      return (
        <StepRow icon={Target}>
          <span className="text-muted-foreground">Modo:</span> <FlowModeBadge mode={step.mode} />
        </StepRow>
      );
    case "tool":
      return (
        <StepRow icon={Wrench}>
          <span className="font-mono text-xs">{step.toolName}</span>{" "}
          <span className="text-muted-foreground">→</span>{" "}
          {step.error ? (
            <span className="text-destructive">error: {step.error}</span>
          ) : (
            <span>{step.summary}</span>
          )}
        </StepRow>
      );
    case "composer": {
      const first = step.messages[0];
      return (
        <StepRow icon={Sparkles}>
          <span className="text-muted-foreground">Bot decidió responder:</span>{" "}
          <span className="italic">
            {step.messages.length === 1 && first
              ? `«${truncate(first, 80)}»`
              : `${step.messages.length} mensajes`}
          </span>
        </StepRow>
      );
    }
    case "outbound":
      return (
        <StepRow icon={SendHorizonal}>
          <span className="text-muted-foreground">
            Envió {step.count} mensaje{step.count > 1 ? "s" : ""}:
          </span>
          <ul className="mt-1 space-y-0.5">
            {step.previews.map((p, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: previews are derived from immutable trace JSON, never reordered.
              <li key={`${i}-${p.slice(0, 12)}`} className="text-xs text-muted-foreground">
                · {truncate(p, 100)}
              </li>
            ))}
          </ul>
        </StepRow>
      );
    case "transition":
      return (
        <StepRow icon={ArrowRight}>
          <span className="text-muted-foreground">Etapa:</span>{" "}
          <span className="font-mono text-xs">{step.from}</span>{" "}
          <ArrowRight className="inline h-3 w-3" />{" "}
          <span className="font-mono text-xs">{step.to}</span>
        </StepRow>
      );
  }
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
    <div className="divide-y rounded-md border">
      {steps.map((step, idx) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: story steps are derived deterministically from the trace and never reordered.
        <div key={`${idx}-${step.kind}`} className="px-3">
          {renderStep(step)}
        </div>
      ))}
    </div>
  );
}

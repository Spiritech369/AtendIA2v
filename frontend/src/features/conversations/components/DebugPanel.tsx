import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Brain,
  Clock,
  Cpu,
  DollarSign,
  Layers,
  Wrench,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { turnTracesApi } from "@/features/turn-traces/api";

interface Props {
  traceId: string;
  onClose: () => void;
}

export function DebugPanel({ traceId, onClose }: Props) {
  const { data: t, isLoading } = useQuery({
    queryKey: ["turn-trace", traceId],
    queryFn: () => turnTracesApi.getOne(traceId),
  });

  if (isLoading || !t) {
    return (
      <PanelShell onClose={onClose} title="Cargando…">
        <div className="space-y-3 p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </PanelShell>
    );
  }

  return (
    <PanelShell
      onClose={onClose}
      title={`Turn ${t.turn_number}`}
      subtitle={t.flow_mode ?? undefined}
    >
      <ScrollArea className="flex-1">
        <div className="space-y-0">
          <OverviewSection trace={t} />
          <Separator />
          <PipelineSection trace={t} />
          <Separator />
          <NluSection trace={t} />
          <Separator />
          <ComposerSection trace={t} />
          {t.tool_calls.length > 0 && (
            <>
              <Separator />
              <ToolCallsSection trace={t} />
            </>
          )}
          <Separator />
          <StateSection trace={t} />
          <Separator />
          <ErrorsSection trace={t} />
        </div>
      </ScrollArea>
    </PanelShell>
  );
}

function PanelShell({
  onClose,
  title,
  subtitle,
  children,
}: {
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full w-96 shrink-0 flex-col overflow-hidden rounded-lg border bg-background shadow-lg">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{title}</span>
          {subtitle && (
            <Badge variant="outline" className="text-[10px]">
              {subtitle}
            </Badge>
          )}
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      {children}
    </div>
  );
}

// ── Overview ────────────────────────────────────────────────────────

function OverviewSection({ trace: t }: { trace: TurnTraceDetail }) {
  const cost = Number(t.total_cost_usd);
  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={Activity} label="Resumen" />
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <Stat icon={Clock} label="Latencia" value={t.total_latency_ms != null ? `${t.total_latency_ms}ms` : "—"} />
        <Stat icon={DollarSign} label="Costo" value={cost > 0 ? `$${cost.toFixed(4)}` : "—"} />
        {t.bot_paused && (
          <div className="col-span-2">
            <Badge variant="secondary" className="text-[10px]">Operador controlaba</Badge>
          </div>
        )}
      </div>
      {t.inbound_text && (
        <div className="rounded-md bg-muted p-2 text-xs italic line-clamp-2">
          {t.inbound_text}
        </div>
      )}
    </div>
  );
}

// ── Pipeline latency bars ───────────────────────────────────────────

function PipelineSection({ trace: t }: { trace: TurnTraceDetail }) {
  const stages = [
    { label: "NLU", ms: t.nlu_latency_ms },
    { label: "Composer", ms: t.composer_latency_ms },
    { label: "Vision", ms: t.vision_latency_ms },
  ].filter((s) => s.ms != null && s.ms > 0) as { label: string; ms: number }[];

  if (stages.length === 0) {
    return (
      <div className="p-3">
        <SectionHeader icon={Layers} label="Pipeline" />
        <div className="mt-1 text-xs text-muted-foreground">Sin datos de latencia.</div>
      </div>
    );
  }

  const maxMs = Math.max(...stages.map((s) => s.ms));

  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={Layers} label="Pipeline" />
      <div className="space-y-1.5">
        {stages.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-xs">
            <span className="w-16 shrink-0 text-muted-foreground">{s.label}</span>
            <div className="relative h-4 flex-1 rounded bg-muted">
              <div
                className="absolute inset-y-0 left-0 rounded bg-indigo-500/80"
                style={{ width: `${(s.ms / maxMs) * 100}%` }}
              />
            </div>
            <span className="w-14 shrink-0 text-right font-mono">{s.ms}ms</span>
          </div>
        ))}
      </div>
      {t.total_latency_ms != null && (
        <div className="text-right text-[10px] text-muted-foreground">
          Total: {t.total_latency_ms}ms
        </div>
      )}
    </div>
  );
}

// ── NLU ─────────────────────────────────────────────────────────────

function NluSection({ trace: t }: { trace: TurnTraceDetail }) {
  const hasData = t.nlu_model || t.nlu_input || t.nlu_output;
  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={Brain} label="NLU" />
      {!hasData ? (
        <div className="text-xs text-muted-foreground">Sin NLU en este turno.</div>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
            {t.nlu_model && <Kv label="Modelo" value={t.nlu_model} />}
            {t.nlu_tokens_in != null && <Kv label="Tokens in" value={String(t.nlu_tokens_in)} />}
            {t.nlu_tokens_out != null && <Kv label="Tokens out" value={String(t.nlu_tokens_out)} />}
            {t.nlu_latency_ms != null && <Kv label="Latencia" value={`${t.nlu_latency_ms}ms`} />}
            {t.nlu_cost_usd && Number(t.nlu_cost_usd) > 0 && (
              <Kv label="Costo" value={`$${Number(t.nlu_cost_usd).toFixed(4)}`} />
            )}
          </div>
          <CollapsibleJson label="NLU input" value={t.nlu_input} />
          <CollapsibleJson label="NLU output" value={t.nlu_output} />
        </>
      )}
    </div>
  );
}

// ── Composer ─────────────────────────────────────────────────────────

function ComposerSection({ trace: t }: { trace: TurnTraceDetail }) {
  const hasData = t.composer_model || t.composer_input || t.composer_output;
  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={Brain} label="Composer" />
      {!hasData ? (
        <div className="text-xs text-muted-foreground">Sin composer en este turno.</div>
      ) : (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
            {t.composer_model && <Kv label="Modelo" value={t.composer_model} />}
            {t.composer_tokens_in != null && <Kv label="Tokens in" value={String(t.composer_tokens_in)} />}
            {t.composer_tokens_out != null && <Kv label="Tokens out" value={String(t.composer_tokens_out)} />}
            {t.composer_latency_ms != null && <Kv label="Latencia" value={`${t.composer_latency_ms}ms`} />}
            {t.composer_cost_usd && Number(t.composer_cost_usd) > 0 && (
              <Kv label="Costo" value={`$${Number(t.composer_cost_usd).toFixed(4)}`} />
            )}
          </div>
          <CollapsibleJson label="Composer input" value={t.composer_input} />
          <CollapsibleJson label="Composer output" value={t.composer_output} />
        </>
      )}
    </div>
  );
}

// ── Tool calls ──────────────────────────────────────────────────────

function ToolCallsSection({ trace: t }: { trace: TurnTraceDetail }) {
  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={Wrench} label={`Tool calls (${t.tool_calls.length})`} />
      <div className="space-y-1.5">
        {t.tool_calls.map((tc) => (
          <details key={tc.id} className="group rounded border text-xs">
            <summary className="flex cursor-pointer items-center gap-2 px-2 py-1.5 hover:bg-muted/50">
              <span className="font-mono font-medium">{tc.tool_name}</span>
              {tc.latency_ms != null && (
                <span className="text-muted-foreground">{tc.latency_ms}ms</span>
              )}
              {tc.error && (
                <Badge variant="destructive" className="ml-auto h-4 px-1 text-[10px]">
                  error
                </Badge>
              )}
            </summary>
            <div className="space-y-1 border-t p-2">
              <CollapsibleJson label="Input" value={tc.input_payload} defaultOpen />
              {tc.output_payload && <CollapsibleJson label="Output" value={tc.output_payload} />}
              {tc.error && (
                <div className="rounded bg-destructive/10 p-1.5 text-destructive">{tc.error}</div>
              )}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

// ── State ───────────────────────────────────────────────────────────

function StateSection({ trace: t }: { trace: TurnTraceDetail }) {
  const hasState = t.state_before || t.state_after || t.stage_transition;
  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={ArrowRight} label="Estado" />
      {!hasState ? (
        <div className="text-xs text-muted-foreground">Sin cambios de estado.</div>
      ) : (
        <>
          {t.stage_transition && (
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">Transición:</span>
              <Badge variant="outline" className="font-mono text-[10px]">
                {t.stage_transition}
              </Badge>
            </div>
          )}
          <CollapsibleJson label="Antes" value={t.state_before} />
          <CollapsibleJson label="Después" value={t.state_after} />
        </>
      )}
    </div>
  );
}

// ── Errors ──────────────────────────────────────────────────────────

function ErrorsSection({ trace: t }: { trace: TurnTraceDetail }) {
  const errors = t.errors ?? [];
  return (
    <div className="space-y-2 p-3">
      <SectionHeader icon={AlertTriangle} label="Errores" />
      {errors.length === 0 ? (
        <div className="text-xs text-emerald-600">Ninguno</div>
      ) : (
        <div className="space-y-1">
          {errors.map((err, i) => (
            <div key={i} className="rounded bg-destructive/10 p-2 text-xs text-destructive">
              {typeof err === "string" ? err : JSON.stringify(err, null, 2)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Shared primitives ───────────────────────────────────────────────

function SectionHeader({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
      <Icon className="h-3 w-3" />
      {label}
    </div>
  );
}

function Stat({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <Icon className="h-3 w-3 text-muted-foreground" />
      <span className="text-muted-foreground">{label}:</span>
      <span className="font-mono font-medium">{value}</span>
    </div>
  );
}

function Kv({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

function CollapsibleJson({
  label,
  value,
  defaultOpen = false,
}: {
  label: string;
  value: unknown;
  defaultOpen?: boolean;
}) {
  if (value == null) return null;
  return (
    <details open={defaultOpen || undefined}>
      <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground">
        {label}
      </summary>
      <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted p-2 text-[11px]">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

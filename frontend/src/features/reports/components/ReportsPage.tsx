// Reports MVP — one screen, four cards. The dueño-comprador opens
// this, sees the numbers, closes. No filters, no export — when
// operators ask for those, they get their own page.
//
// Vertical-agnostic by design: the funnel reads from the tenant's
// own pipeline (whatever stages they configured) and the rest of the
// metrics are channel-shape-independent.
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  Layers,
  MessageSquare,
  RefreshCcw,
  Timer,
  UserCog,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { type FunnelStage, type ReportsOverview, reportsApi } from "@/features/reports/api";
import { cn } from "@/lib/utils";

const REFRESH_INTERVAL_MS = 30_000;

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) {
    const m = Math.floor(minutes);
    const s = Math.round(seconds - m * 60);
    return s === 0 ? `${m}m` : `${m}m ${s}s`;
  }
  const hours = minutes / 60;
  if (hours < 24) {
    const h = Math.floor(hours);
    const m = Math.round(minutes - h * 60);
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  }
  const days = hours / 24;
  return `${days.toFixed(1)} d`;
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffSec = Math.round((Date.now() - d.getTime()) / 1000);
  if (diffSec < 5) return "hace instantes";
  if (diffSec < 60) return `hace ${diffSec}s`;
  if (diffSec < 3600) return `hace ${Math.round(diffSec / 60)}m`;
  return d.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
}

function MetricRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-2xl font-semibold tabular-nums">{value}</span>
        {hint && <span className="text-[10px] text-muted-foreground">{hint}</span>}
      </div>
    </div>
  );
}

function ConversationsCard({ data }: { data: ReportsOverview["conversations"] }) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
        <MessageSquare className="h-4 w-4 text-sky-500" />
        <CardTitle className="text-sm font-semibold">Conversaciones nuevas</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-0">
        <MetricRow label="Hoy" value={String(data.today)} />
        <MetricRow label="Esta semana" value={String(data.this_week)} />
        <MetricRow label="Este mes" value={String(data.this_month)} />
      </CardContent>
    </Card>
  );
}

function FirstResponseCard({ data }: { data: ReportsOverview["first_response"] }) {
  const value = formatDuration(data.avg_seconds);
  const hasSample = data.sample_size > 0;
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
        <Timer className="h-4 w-4 text-emerald-500" />
        <CardTitle className="text-sm font-semibold">Primera respuesta promedio</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-2 pt-0">
        <div className="font-mono text-4xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground">
          {hasSample
            ? `Sobre ${data.sample_size} conversación${data.sample_size === 1 ? "" : "es"} en los últimos ${data.window_days} días.`
            : `Sin conversaciones cerradas con respuesta en los últimos ${data.window_days} días.`}
        </div>
      </CardContent>
    </Card>
  );
}

function HandoffCard({ data }: { data: ReportsOverview["handoff"] }) {
  const pct = data.handoff_rate_pct;
  const tone = pct >= 50 ? "text-rose-600" : pct >= 25 ? "text-amber-500" : "text-emerald-500";
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
        <UserCog className="h-4 w-4 text-violet-500" />
        <CardTitle className="text-sm font-semibold">Tasa de handoff</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-2 pt-0">
        <div className={cn("font-mono text-4xl font-semibold tabular-nums", tone)}>
          {pct.toFixed(1)}%
        </div>
        <div className="text-xs text-muted-foreground">
          {data.handed_off} de {data.total_conversations} conversaciones escalaron a humano en los
          últimos {data.window_days} días.
        </div>
      </CardContent>
    </Card>
  );
}

function FunnelRow({ stage, peak }: { stage: FunnelStage; peak: number }) {
  const widthPct = peak > 0 ? Math.min(100, (stage.reached_count / peak) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium">{stage.label}</span>
        <span className="font-mono text-muted-foreground">
          {stage.current_count} aquí · {stage.reached_count} llegaron
          {stage.conversion_pct != null && (
            <span className="ml-1">({stage.conversion_pct.toFixed(0)}%)</span>
          )}
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded bg-muted">
        <div
          className="absolute inset-y-0 left-0 rounded bg-sky-500"
          style={{ width: `${widthPct}%` }}
        />
      </div>
    </div>
  );
}

function FunnelCard({ stages }: { stages: FunnelStage[] }) {
  const peak = stages.reduce((max, s) => Math.max(max, s.reached_count), 0);
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
        <Layers className="h-4 w-4 text-amber-500" />
        <CardTitle className="text-sm font-semibold">Funnel del pipeline</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5 pt-0">
        {stages.length === 0 ? (
          <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
            Sin pipeline configurado todavía. Una vez que tengas etapas, verás aquí cuánta gente
            está en cada una.
          </div>
        ) : (
          stages.map((s) => <FunnelRow key={s.stage_id} stage={s} peak={peak} />)
        )}
      </CardContent>
    </Card>
  );
}

function HeaderBar({
  generatedAt,
  isFetching,
}: {
  generatedAt: string | null;
  isFetching: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-1">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold">Reports</h1>
        <Badge variant="outline" className="text-[10px]">
          <CalendarDays className="mr-1 h-3 w-3" />
          Vista general
        </Badge>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        {generatedAt && <span>Datos: {formatRelative(generatedAt)}</span>}
        <RefreshCcw className={cn("h-3 w-3", isFetching && "animate-spin")} />
        <span>refresh 30s</span>
      </div>
    </div>
  );
}

function TrendHint({ value }: { value: number | null | undefined }) {
  // Reserved for future deltas vs prior period. For MVP we don't have a
  // baseline to compare against, but the component shape stays ready.
  if (value == null) return null;
  const positive = value >= 0;
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center text-[10px]",
        positive ? "text-emerald-500" : "text-rose-500",
      )}
    >
      <Icon className="h-3 w-3" />
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}

export function ReportsPage() {
  const query = useQuery({
    queryKey: ["reports", "overview"],
    queryFn: reportsApi.getOverview,
    refetchInterval: REFRESH_INTERVAL_MS,
  });

  if (query.isLoading) {
    return (
      <div className="space-y-4 p-4">
        <Skeleton className="h-8 w-40" />
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={`sk-${i}`} className="h-48 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-4 p-4">
        <HeaderBar generatedAt={null} isFetching={query.isFetching} />
        <Card>
          <CardContent className="py-6 text-sm text-destructive">
            No se pudieron cargar las métricas. Reintentando…
          </CardContent>
        </Card>
      </div>
    );
  }

  const data = query.data;

  return (
    <div className="space-y-4 p-4">
      <HeaderBar generatedAt={data.generated_at} isFetching={query.isFetching} />
      <div className="grid gap-4 md:grid-cols-2">
        <ConversationsCard data={data.conversations} />
        <FirstResponseCard data={data.first_response} />
        <HandoffCard data={data.handoff} />
        <FunnelCard stages={data.pipeline_funnel} />
      </div>
      {/* Placeholder for future "vs período anterior" trend strip. */}
      <TrendHint value={null} />
    </div>
  );
}

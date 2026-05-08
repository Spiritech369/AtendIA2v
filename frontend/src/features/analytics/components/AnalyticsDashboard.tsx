import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { analyticsApi } from "@/features/analytics/api";
import { cn } from "@/lib/utils";

function pct(num: number, den: number): string {
  if (den === 0) return "—";
  return `${Math.round((num / den) * 100)}%`;
}

function FunnelCard() {
  const q = useQuery({ queryKey: ["analytics", "funnel"], queryFn: () => analyticsApi.funnel() });
  if (q.isLoading || !q.data) return <Skeleton className="h-64 w-full" />;
  const { total_conversations, quoted, plan_assigned, papeleria_completa } = q.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Embudo</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {[
          { label: "Conversaciones", value: total_conversations, of: total_conversations },
          { label: "Cotizadas (modelo_moto)", value: quoted, of: total_conversations },
          { label: "Plan asignado", value: plan_assigned, of: total_conversations },
          {
            label: "Papelería completa",
            value: papeleria_completa,
            of: total_conversations,
          },
        ].map((row) => {
          const w = row.of === 0 ? 0 : (row.value / row.of) * 100;
          return (
            <div key={row.label} className="space-y-1">
              <div className="flex justify-between text-sm">
                <span>{row.label}</span>
                <span className="font-mono text-xs">
                  {row.value} ({pct(row.value, row.of)})
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary" style={{ width: `${w}%` }} />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function CostCard() {
  const q = useQuery({ queryKey: ["analytics", "cost"], queryFn: () => analyticsApi.cost() });
  if (q.isLoading || !q.data) return <Skeleton className="h-64 w-full" />;
  const points = q.data.points;
  const total = points.reduce((a, p) => a + Number.parseFloat(p.total_usd), 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Costo por día (USD)</CardTitle>
        <div className="text-xs text-muted-foreground">Total: ${total.toFixed(4)}</div>
      </CardHeader>
      <CardContent>
        {points.length === 0 ? (
          <div className="py-4 text-sm text-muted-foreground">Sin datos.</div>
        ) : (
          <div className="space-y-1">
            {points.slice(-14).map((p) => {
              const v = Number.parseFloat(p.total_usd);
              const max = Math.max(...points.map((x) => Number.parseFloat(x.total_usd)), 0.0001);
              return (
                <div key={p.day} className="flex items-center gap-2 text-xs">
                  <span className="w-24 font-mono text-muted-foreground">{p.day.slice(0, 10)}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded bg-muted">
                    <div className="h-full bg-primary" style={{ width: `${(v / max) * 100}%` }} />
                  </div>
                  <span className="w-20 text-right font-mono">${v.toFixed(4)}</span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function VolumeCard() {
  const q = useQuery({
    queryKey: ["analytics", "volume"],
    queryFn: () => analyticsApi.volume(),
  });
  if (q.isLoading || !q.data) return <Skeleton className="h-48 w-full" />;
  const buckets = q.data.buckets;
  const max = Math.max(...buckets.map((b) => b.inbound + b.outbound), 1);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Volumen por hora</CardTitle>
        <div className="text-xs text-muted-foreground">UTC. Verde = inbound, azul = outbound.</div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-24 gap-px">
          {buckets.map((b) => {
            const ratio = (b.inbound + b.outbound) / max;
            return (
              <div
                key={b.hour}
                className="flex h-16 items-end"
                title={`${b.hour}:00 — in:${b.inbound} out:${b.outbound}`}
              >
                <div
                  className={cn("w-full rounded-t", ratio === 0 ? "bg-muted" : "bg-primary/60")}
                  style={{ height: `${ratio * 100}%` }}
                />
              </div>
            );
          })}
        </div>
        <div className="mt-1 grid grid-cols-24 gap-px text-[10px] text-muted-foreground">
          {buckets.map((b) => (
            <div key={b.hour} className="text-center">
              {b.hour}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function AnalyticsDashboard() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Analítica</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <FunnelCard />
        <CostCard />
      </div>
      <VolumeCard />
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  Bot,
  Calendar,
  CalendarDays,
  CheckCircle2,
  Circle,
  KanbanSquare,
  MessageSquare,
  Sparkles,
  Upload,
  UserPlus,
  Users,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { dashboardApi } from "@/features/dashboard/api";
import { useAuthStore } from "@/stores/auth";

const APPT_STATUS: Record<string, { label: string; cls: string }> = {
  scheduled: { label: "Programada", cls: "bg-blue-500/15 text-blue-700 dark:text-blue-300" },
  completed: { label: "Completada", cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  cancelled: { label: "Cancelada", cls: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400" },
  no_show: { label: "No asistió", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
}

function relativeFromNow(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "ahora";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d`;
  return new Date(iso).toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
}

function formatChartDate(date: string): string {
  const d = new Date(date + "T00:00:00");
  return d.toLocaleDateString("es-MX", { weekday: "short", day: "2-digit" });
}

function todayGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Buenos días";
  if (hour < 19) return "Buenas tardes";
  return "Buenas noches";
}

export function DashboardPage() {
  const me = useAuthStore((s) => s.user);
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: dashboardApi.summary,
    refetchInterval: 60_000,
  });

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const data = query.data;
  if (!data) {
    return <div className="text-sm text-muted-foreground">No hay datos.</div>;
  }

  const isNew =
    data.total_customers === 0 &&
    data.conversations_today === 0 &&
    data.recent_conversations.length === 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {todayGreeting()}{me?.email ? `, ${me.email.split("@")[0]}` : ""}
          </h1>
          <p className="text-sm text-muted-foreground">
            {new Date().toLocaleDateString("es-MX", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </p>
        </div>
        <QuickActions />
      </div>

      {isNew && <OnboardingCard />}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={Users}
          label="Clientes totales"
          value={data.total_customers}
          accent="blue"
          to="/customers"
        />
        <StatCard
          icon={MessageSquare}
          label="Conversaciones hoy"
          value={data.conversations_today}
          accent="emerald"
          to="/conversations/$conversationId"
          disabled
        />
        <StatCard
          icon={Activity}
          label="Activas"
          value={data.active_conversations}
          accent="purple"
        />
        <StatCard
          icon={Sparkles}
          label="Sin responder"
          value={data.unanswered_conversations}
          accent={data.unanswered_conversations > 0 ? "amber" : "zinc"}
          highlight={data.unanswered_conversations > 0}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <div>
              <CardTitle className="text-base">Actividad últimos 7 días</CardTitle>
              <p className="text-xs text-muted-foreground">Mensajes inbound vs outbound</p>
            </div>
          </CardHeader>
          <CardContent className="h-72">
            {data.activity_chart.every((d) => d.inbound === 0 && d.outbound === 0) ? (
              <EmptyChart />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.activity_chart} barCategoryGap={8}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-muted" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={formatChartDate}
                  />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={(label) => formatChartDate(String(label))}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Bar dataKey="inbound" fill="#16a34a" name="Recibidos" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="outbound" fill="#2563eb" name="Enviados" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarDays className="h-4 w-4" /> Citas de hoy
            </CardTitle>
            <Link to="/appointments" className="text-xs text-primary hover:underline">
              Ver todas
            </Link>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {data.todays_appointments.length === 0 ? (
              <div className="rounded-md border border-dashed py-6 text-center text-xs text-muted-foreground">
                Sin citas para hoy
              </div>
            ) : (
              data.todays_appointments.map((a) => {
                const status = APPT_STATUS[a.status] ?? { label: a.status, cls: "" };
                return (
                  <div key={a.id} className="rounded-md border p-2.5 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-medium">
                          {a.customer_name ?? a.customer_phone}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {formatTime(a.scheduled_at)} · {a.service}
                        </div>
                      </div>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${status.cls}`}>
                        {status.label}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <MessageSquare className="h-4 w-4" /> Conversaciones recientes
          </CardTitle>
          <Link to="/handoffs" className="text-xs text-primary hover:underline">
            Bandeja
          </Link>
        </CardHeader>
        <CardContent className="pt-0">
          {data.recent_conversations.length === 0 ? (
            <div className="rounded-md border border-dashed py-6 text-center text-xs text-muted-foreground">
              No hay conversaciones aún
            </div>
          ) : (
            <div className="divide-y rounded-md border">
              {data.recent_conversations.map((c) => (
                <Link
                  key={c.id}
                  to="/conversations/$conversationId"
                  params={{ conversationId: c.id }}
                  className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm hover:bg-muted/50"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">
                        {c.customer_name ?? c.customer_phone}
                      </span>
                      {c.unread_count > 0 && (
                        <Badge className="h-4 min-w-[16px] px-1 text-[10px]">
                          {c.unread_count}
                        </Badge>
                      )}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {c.customer_phone}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <Badge variant="outline" className="text-[10px] capitalize">
                      {c.current_stage.replace(/_/g, " ")}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {relativeFromNow(c.last_activity_at)}
                    </span>
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

const ACCENT_CLASSES: Record<string, { icon: string; ring: string }> = {
  blue: { icon: "bg-blue-500/15 text-blue-600 dark:text-blue-300", ring: "" },
  emerald: { icon: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300", ring: "" },
  purple: { icon: "bg-purple-500/15 text-purple-600 dark:text-purple-300", ring: "" },
  amber: { icon: "bg-amber-500/15 text-amber-600 dark:text-amber-300", ring: "ring-1 ring-amber-500/40" },
  zinc: { icon: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400", ring: "" },
};

function StatCard({
  icon: Icon,
  label,
  value,
  accent,
  to,
  disabled,
  highlight,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  accent: keyof typeof ACCENT_CLASSES;
  to?: string;
  disabled?: boolean;
  highlight?: boolean;
}) {
  const a = ACCENT_CLASSES[accent] ?? ACCENT_CLASSES.zinc;
  const body = (
    <Card className={`${a?.ring} ${highlight ? "border-amber-500/40" : ""}`}>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={`rounded-md p-2 ${a?.icon}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-2xl font-semibold leading-tight">{value}</div>
        </div>
      </CardContent>
    </Card>
  );
  if (!to || disabled) return body;
  return (
    <Link to={to} className="block transition hover:opacity-90">
      {body}
    </Link>
  );
}

const ONBOARDING_STEPS = [
  {
    label: 'Sube tu catálogo o FAQ en "Conocimiento"',
    to: "/knowledge",
    icon: Upload,
  },
  {
    label: 'Conecta tu WhatsApp en "Configuración → Integraciones"',
    to: "/config",
    icon: Sparkles,
  },
  {
    label: 'Configura las etapas del pipeline en "Configuración → Pipeline"',
    to: "/config",
    icon: KanbanSquare,
  },
  {
    label: 'Crea tu primer agente IA en "Agentes"',
    to: "/agents",
    icon: Bot,
  },
] as const;

function OnboardingCard() {
  return (
    <Card className="border-primary/20 bg-gradient-to-br from-primary/5 via-transparent to-transparent">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          ¿Por dónde empiezo?
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Estos 4 pasos dejan tu asistente listo para atender clientes reales.
        </p>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-2 md:grid-cols-2">
          {ONBOARDING_STEPS.map((step, i) => (
            <li key={i}>
              <Link
                to={step.to}
                className="flex items-start gap-2 rounded-md border bg-background p-3 text-sm hover:border-primary"
              >
                <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <div className="flex-1">
                  <div className="text-xs font-medium text-muted-foreground">
                    Paso {i + 1}
                  </div>
                  <div className="text-sm">{step.label}</div>
                </div>
                <step.icon className="h-4 w-4 shrink-0 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

const QUICK_ACTIONS = [
  { label: "Pipeline", to: "/pipeline", icon: KanbanSquare },
  { label: "Citas", to: "/appointments", icon: Calendar },
  { label: "Cliente nuevo", to: "/customers", icon: UserPlus },
  { label: "Agentes", to: "/agents", icon: Bot },
] as const;

function QuickActions() {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {QUICK_ACTIONS.map((q) => (
        <Link
          key={q.to}
          to={q.to}
          className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-muted"
        >
          <q.icon className="h-3.5 w-3.5" /> {q.label}
        </Link>
      ))}
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <Activity className="h-10 w-10 text-muted-foreground" />
      <div className="text-sm font-medium">Sin actividad esta semana</div>
      <div className="text-xs text-muted-foreground">
        Cuando tu agente reciba o envíe mensajes, aparecerán aquí.
      </div>
    </div>
  );
}

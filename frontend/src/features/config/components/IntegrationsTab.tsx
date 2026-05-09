import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Brain,
  CalendarDays,
  Check,
  Copy,
  Eye,
  EyeOff,
  ExternalLink,
  MessageCircle,
  Sparkles,
  Table2,
} from "lucide-react";
import { useEffect, useState } from "react";
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
import { integrationsApi, tenantsApi } from "@/features/config/api";

const COMMON_TIMEZONES = [
  "America/Mexico_City",
  "America/Tijuana",
  "America/Monterrey",
  "America/Cancun",
  "America/Bogota",
  "America/Lima",
  "America/Santiago",
  "America/Buenos_Aires",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/Madrid",
  "UTC",
];

function relativeFromNow(iso: string | null): string {
  if (!iso) return "nunca";
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "hace unos segundos";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  return `hace ${days} d`;
}

export function IntegrationsTab() {
  const details = useQuery({
    queryKey: ["integrations", "whatsapp"],
    queryFn: integrationsApi.getWhatsAppDetails,
    refetchInterval: 30_000,
  });
  const aiProvider = useQuery({
    queryKey: ["integrations", "ai-provider"],
    queryFn: integrationsApi.getAIProvider,
  });
  const timezone = useQuery({
    queryKey: ["tenants", "timezone"],
    queryFn: tenantsApi.getTimezone,
  });

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <WhatsAppCard details={details.data} loading={details.isLoading} />
      <AIProviderCard info={aiProvider.data} loading={aiProvider.isLoading} />
      <TimezoneCard value={timezone.data?.timezone ?? "America/Mexico_City"} loading={timezone.isLoading} />
      <ExportCard
        icon={Table2}
        title="Google Sheets"
        description="Exporta clientes con documentos completos a una hoja de cálculo."
        instructions={[
          "Abre Configuración → Datos → Exportar clientes para descargar un CSV manualmente.",
          "Para sincronización automática, contacta a soporte: el conector requiere una cuenta de servicio.",
        ]}
      />
      <ExportCard
        icon={CalendarDays}
        title="Google Calendar"
        description="Refleja las citas creadas por el agente en un calendario compartido."
        instructions={[
          "Las citas ya se guardan en /citas y se pueden suscribir vía API REST.",
          "Para sincronizar a Google Calendar contacta a soporte: requiere OAuth por usuario.",
        ]}
      />
    </div>
  );
}

function StatusDot({ status }: { status: "connected" | "inactive" | "paused" | "loading" }) {
  const config = {
    connected: { color: "bg-emerald-500", label: "Conectado", pulse: false },
    inactive: { color: "bg-amber-500", label: "Sin actividad reciente", pulse: true },
    paused: { color: "bg-red-500", label: "Pausado (circuit breaker)", pulse: false },
    loading: { color: "bg-zinc-400", label: "Consultando…", pulse: true },
  }[status];
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`relative flex h-2 w-2`}>
        {config.pulse && (
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${config.color} opacity-50`} />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${config.color}`} />
      </span>
      <span className="text-muted-foreground">{config.label}</span>
    </div>
  );
}

function WhatsAppCard({
  details,
  loading,
}: {
  details: ReturnType<typeof useQuery<unknown>>["data"] extends infer T ? T : never;
  loading: boolean;
}) {
  if (loading || !details) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageCircle className="h-4 w-4" /> WhatsApp Cloud
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    );
  }
  // Re-narrow `details` to the real shape (the Card-component generic above
  // can't see across module boundaries cleanly, so we cast at use-site).
  const d = details as {
    phone_number: string | null;
    business_name: string | null;
    phone_number_id: string | null;
    business_id: string | null;
    verify_token: string | null;
    webhook_path: string;
    last_webhook_at: string | null;
    circuit_breaker_open: boolean;
  };

  const status: "connected" | "inactive" | "paused" = d.circuit_breaker_open
    ? "paused"
    : d.last_webhook_at && Date.now() - new Date(d.last_webhook_at).getTime() < 5 * 60_000
      ? "connected"
      : "inactive";

  const webhookUrl = typeof window !== "undefined" ? window.location.origin + d.webhook_path : d.webhook_path;
  const isConfigured = Boolean(d.phone_number_id);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2">
            <MessageCircle className="h-4 w-4" /> WhatsApp Cloud
          </CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Canal principal — recibe y responde por WhatsApp Business API.
          </p>
        </div>
        <StatusDot status={status} />
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!isConfigured && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
            <span>
              No hay credenciales de Meta configuradas para este tenant. Pídelas a tu administrador.
            </span>
          </div>
        )}

        <div className="grid gap-1.5">
          <Info label="Negocio" value={d.business_name} />
          <Info label="Teléfono" value={d.phone_number} />
          <Info label="Phone number ID" value={d.phone_number_id} mono />
          <Info label="Business ID" value={d.business_id} mono />
          <Info label="Último webhook" value={relativeFromNow(d.last_webhook_at)} />
        </div>

        <div className="space-y-2 rounded-md border bg-muted/30 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Configuración Meta
          </div>
          <CopyField label="Webhook URL" value={webhookUrl} />
          <CopyField label="Verify token" value={d.verify_token} secret />
        </div>

        <details className="rounded-md border bg-muted/20 p-3 text-xs">
          <summary className="cursor-pointer font-medium">Instrucciones de configuración</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-4 text-muted-foreground">
            <li>Entra a Meta Business Manager → tu app → WhatsApp → Configuración.</li>
            <li>En "Webhook" haz clic en Editar.</li>
            <li>Pega la URL de arriba en "URL de devolución de llamada".</li>
            <li>Pega el verify token en "Token de verificación".</li>
            <li>Guarda y suscribe a los campos <code>messages</code>.</li>
          </ol>
        </details>
      </CardContent>
    </Card>
  );
}

function CopyField({ label, value, secret }: { label: string; value: string | null; secret?: boolean }) {
  const [revealed, setRevealed] = useState(false);
  if (!value) {
    return (
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">—</span>
      </div>
    );
  }
  const display = secret && !revealed ? "•".repeat(Math.min(value.length, 18)) : value;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <Label className="text-xs">{label}</Label>
        <div className="flex items-center gap-1">
          {secret && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setRevealed((r) => !r)}
              title={revealed ? "Ocultar" : "Mostrar"}
            >
              {revealed ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => {
              void navigator.clipboard.writeText(value).then(() => toast.success(`${label} copiado`));
            }}
            title="Copiar"
          >
            <Copy className="h-3 w-3" />
          </Button>
        </div>
      </div>
      <code className="block break-all rounded border bg-background px-2 py-1 font-mono text-[11px]">
        {display}
      </code>
    </div>
  );
}

function AIProviderCard({
  info,
  loading,
}: {
  info: ReturnType<typeof useQuery<unknown>>["data"] extends infer T ? T : never;
  loading: boolean;
}) {
  if (loading || !info) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4" /> Proveedor de IA
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }
  const i = info as {
    nlu_provider: string;
    nlu_model: string;
    composer_provider: string;
    composer_model: string;
    has_openai_key: boolean;
  };
  const usingFallback = i.nlu_provider === "keyword" || i.composer_provider === "canned";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Brain className="h-4 w-4" /> Proveedor de IA
        </CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          Configurado en variables de entorno del servidor (no editable desde la UI).
        </p>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {usingFallback && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
            <span>
              Algún componente está usando el modo de respaldo (sin LLM). Verifica
              <code className="mx-1">ATENDIA_V2_NLU_PROVIDER</code> y <code>ATENDIA_V2_COMPOSER_PROVIDER</code>.
            </span>
          </div>
        )}
        <ProviderRow
          label="NLU (clasificación)"
          provider={i.nlu_provider}
          model={i.nlu_model}
          fallback="keyword"
        />
        <ProviderRow
          label="Composer (respuestas)"
          provider={i.composer_provider}
          model={i.composer_model}
          fallback="canned"
        />
        <div className="flex items-center justify-between rounded-md border px-3 py-2 text-xs">
          <span className="text-muted-foreground">OpenAI API key</span>
          <Badge variant={i.has_openai_key ? "default" : "secondary"} className="gap-1">
            {i.has_openai_key ? <Check className="h-3 w-3" /> : null}
            {i.has_openai_key ? "Configurada" : "No configurada"}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}

function ProviderRow({
  label,
  provider,
  model,
  fallback,
}: {
  label: string;
  provider: string;
  model: string;
  fallback: string;
}) {
  const isFallback = provider === fallback;
  return (
    <div className="flex items-center justify-between rounded-md border px-3 py-2 text-xs">
      <div>
        <div className="font-medium">{label}</div>
        <div className="text-muted-foreground">{model}</div>
      </div>
      <Badge variant={isFallback ? "secondary" : "default"}>
        {provider}
      </Badge>
    </div>
  );
}

function TimezoneCard({ value, loading }: { value: string; loading: boolean }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(value);
  const [custom, setCustom] = useState(!COMMON_TIMEZONES.includes(value));
  useEffect(() => {
    setDraft(value);
    setCustom(!COMMON_TIMEZONES.includes(value));
  }, [value]);

  const save = useMutation({
    mutationFn: tenantsApi.putTimezone,
    onSuccess: () => {
      toast.success("Zona horaria actualizada");
      void qc.invalidateQueries({ queryKey: ["tenants", "timezone"] });
    },
    onError: (e) => toast.error("No se pudo guardar", { description: e.message }),
  });

  const localTime = (() => {
    try {
      return new Date().toLocaleTimeString("es-MX", {
        timeZone: draft,
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "—";
    }
  })();

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Zona horaria</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Zona horaria</CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          Define cómo se calculan "hoy", horarios de atención y agendado de citas.
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!custom ? (
          <div>
            <Label>Selecciona una zona</Label>
            <Select
              value={COMMON_TIMEZONES.includes(draft) ? draft : "America/Mexico_City"}
              onValueChange={(v) => {
                if (v === "__custom__") {
                  setCustom(true);
                } else {
                  setDraft(v);
                }
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMMON_TIMEZONES.map((tz) => (
                  <SelectItem key={tz} value={tz}>
                    {tz.replace(/_/g, " ")}
                  </SelectItem>
                ))}
                <SelectItem value="__custom__">Otra…</SelectItem>
              </SelectContent>
            </Select>
          </div>
        ) : (
          <div>
            <div className="flex items-center justify-between">
              <Label>Zona personalizada</Label>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setCustom(false)}
              >
                Volver al listado
              </Button>
            </div>
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ej. Pacific/Auckland"
              className="font-mono text-xs"
            />
          </div>
        )}
        <div className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2 text-xs">
          <span className="text-muted-foreground">Hora local en {draft || "?"}</span>
          <span className="font-mono">{localTime}</span>
        </div>
        <Button
          onClick={() => save.mutate(draft)}
          disabled={save.isPending || draft === value || !draft.trim()}
        >
          {save.isPending ? "Guardando..." : "Guardar"}
        </Button>
      </CardContent>
    </Card>
  );
}

function Info({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-1.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? "truncate font-mono text-[11px]" : "truncate"}>
        {value ?? "—"}
      </span>
    </div>
  );
}

function ExportCard({
  icon: Icon,
  title,
  description,
  instructions,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  instructions: string[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Icon className="h-4 w-4" /> {title}
        </CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <Badge variant="secondary" className="gap-1">
          <ExternalLink className="h-3 w-3" /> Vía API
        </Badge>
        <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
          {instructions.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Brain,
  Building2,
  CalendarCheck,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  FileSpreadsheet,
  Globe,
  Info,
  Lock,
  Mail,
  MessageCircle,
  RefreshCw,
  Settings2,
  Shield,
  Sparkles,
  WifiOff,
  XCircle,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { AIProviderInfo, WhatsAppDetails } from "@/features/config/api";
import { integrationsApi, tenantsApi } from "@/features/config/api";
import { BaileysCard } from "@/features/config/components/BaileysCard";
import { useAuthStore } from "@/stores/auth";

// ─── Constants ────────────────────────────────────────────────────────────────

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

interface ProviderMeta {
  name: string;
  endpoint: string;
  isFallback: boolean;
}

function resolveProvider(provider: string): ProviderMeta {
  const p = provider.toLowerCase();
  if (p.includes("anthropic") || p.includes("claude"))
    return { name: "Claude (Anthropic)", endpoint: "https://api.anthropic.com", isFallback: false };
  if (p.includes("openai") || p === "gpt")
    return { name: "OpenAI", endpoint: "https://api.openai.com", isFallback: false };
  if (p === "keyword")
    return { name: "Keyword matching", endpoint: "—", isFallback: true };
  if (p === "canned")
    return { name: "Respuestas predefinidas", endpoint: "—", isFallback: true };
  return { name: provider, endpoint: "—", isFallback: false };
}

// ─── Types ────────────────────────────────────────────────────────────────────

type WAStatus = "connected" | "needs_attention" | "disconnected" | "paused";

const WA_STATUS_META: Record<
  WAStatus,
  { label: string; icon: typeof Check; bg: string; fg: string; border: string }
> = {
  connected: {
    label: "Conectado",
    icon: CheckCircle2,
    bg: "bg-emerald-500/10",
    fg: "text-emerald-700 dark:text-emerald-300",
    border: "border-emerald-500/30",
  },
  needs_attention: {
    label: "Requiere atención",
    icon: AlertTriangle,
    bg: "bg-amber-500/10",
    fg: "text-amber-700 dark:text-amber-300",
    border: "border-amber-500/30",
  },
  disconnected: {
    label: "Desconectado",
    icon: WifiOff,
    bg: "bg-red-500/10",
    fg: "text-red-700 dark:text-red-300",
    border: "border-red-500/30",
  },
  paused: {
    label: "Solo lectura",
    icon: Shield,
    bg: "bg-blue-500/10",
    fg: "text-blue-700 dark:text-blue-300",
    border: "border-blue-500/30",
  },
};

interface CheckStep {
  title: string;
  desc: string;
  ok: boolean;
  statusLabel: string;
  fixLabel: string;
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function relativeFromNow(iso: string | null): string {
  if (!iso) return "nunca";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return "hace unos segundos";
  if (mins < 60) return `hace ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `hace ${hrs} h`;
  return `hace ${Math.round(hrs / 24)} d`;
}

function waStatus(d: WhatsAppDetails): WAStatus {
  if (!d.phone_number_id) return "disconnected";
  if (d.circuit_breaker_open) return "paused";
  if (d.last_webhook_at) {
    if (Date.now() - new Date(d.last_webhook_at).getTime() < 24 * 60 * 60_000) return "connected";
  }
  return "needs_attention";
}

function buildChecklist(d: WhatsAppDetails): CheckStep[] {
  const ageMs = d.last_webhook_at
    ? Date.now() - new Date(d.last_webhook_at).getTime()
    : Infinity;
  return [
    {
      title: "Credenciales Meta presentes",
      desc: "Phone Number ID configurado en variables de entorno.",
      ok: Boolean(d.phone_number_id),
      statusLabel: d.phone_number_id ? "Detectadas" : "No configuradas",
      fixLabel: "Configurar credenciales",
    },
    {
      title: "Verify token configurado",
      desc: "Token de verificación de webhook presente.",
      ok: Boolean(d.verify_token),
      statusLabel: d.verify_token ? "Configurado" : "Falta",
      fixLabel: "Configurar token",
    },
    {
      title: "Webhook recibido en últimas 24h",
      desc: "Última comunicación recibida desde Meta.",
      ok: ageMs < 24 * 60 * 60_000,
      statusLabel: d.last_webhook_at ? relativeFromNow(d.last_webhook_at) : "Nunca",
      fixLabel: "Enviar prueba",
    },
    {
      title: "Circuit breaker cerrado",
      desc: "El canal no está en pausa automática por errores.",
      ok: !d.circuit_breaker_open,
      statusLabel: d.circuit_breaker_open ? "Abierto" : "Cerrado",
      fixLabel: "Ver detalles",
    },
  ];
}

// ─── CopyField ────────────────────────────────────────────────────────────────

function CopyField({
  label,
  value,
  secret = false,
  isAdmin = true,
  successMsg,
}: {
  label: string;
  value: string | null;
  secret?: boolean;
  isAdmin?: boolean;
  successMsg?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  const [flashing, setFlashing] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function handleCopy() {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      toast.success(successMsg ?? `${label} copiado`);
      setFlashing(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setFlashing(false), 1050);
    } catch {
      toast.error("No se pudo copiar");
    }
  }

  if (!value) {
    return (
      <div className="flex items-center justify-between gap-2 py-1 text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="text-muted-foreground">—</span>
      </div>
    );
  }

  if (secret && !isAdmin) {
    return (
      <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs">
        <Lock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="text-muted-foreground">
          Solo administradores pueden ver este token.
        </span>
      </div>
    );
  }

  const display = secret && !revealed ? "•".repeat(Math.min(value.length, 24)) : value;

  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="flex items-center gap-1.5">
        <code
          className={`flex-1 truncate rounded-md border px-3 py-1.5 font-mono text-[11px] transition-all duration-200 ${
            flashing
              ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "border-border bg-muted/30"
          }`}
        >
          {display}
        </code>
        {secret && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => setRevealed((r) => !r)}
            title={revealed ? "Ocultar valor" : "Mostrar valor"}
            aria-label={revealed ? "Ocultar valor" : "Mostrar valor"}
          >
            {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={handleCopy}
          title={`Copiar ${label}`}
          aria-label={`Copiar ${label}`}
        >
          {flashing ? (
            <Check className="h-3.5 w-3.5 text-emerald-600" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>
    </div>
  );
}

// ─── InfoRow ──────────────────────────────────────────────────────────────────

function InfoRow({
  label,
  value,
  mono = false,
  href,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
  href?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-1">
        <span className={`min-w-0 truncate ${mono ? "font-mono text-[11px]" : ""}`}>
          {value ?? "—"}
        </span>
        {href && value && (
          <a href={href} target="_blank" rel="noopener noreferrer" title="Abrir en nueva pestaña">
            <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground hover:text-foreground" />
          </a>
        )}
      </div>
    </div>
  );
}

// ─── ChecklistStep ────────────────────────────────────────────────────────────

function ChecklistStep({ step }: { step: CheckStep }) {
  return (
    <div className="flex items-start gap-3 py-2.5">
      <div
        className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${
          step.ok
            ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            : "bg-red-500/15 text-red-600 dark:text-red-400"
        }`}
      >
        {step.ok ? <Check className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium">{step.title}</span>
          <span
            className={`shrink-0 text-[10px] font-medium ${
              step.ok
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-600 dark:text-red-400"
            }`}
          >
            {step.statusLabel}
          </span>
        </div>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{step.desc}</p>
        {!step.ok && (
          <button
            type="button"
            className="mt-1 text-[11px] font-medium text-primary underline-offset-2 hover:underline"
          >
            {step.fixLabel} →
          </button>
        )}
      </div>
    </div>
  );
}

// ─── WhatsApp Hero Card ───────────────────────────────────────────────────────

function WhatsAppHeroCard({
  details,
  loading,
}: {
  details: WhatsAppDetails | undefined;
  loading: boolean;
}) {
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [techOpen, setTechOpen] = useState(false);
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "tenant_admin" || user?.role === "superadmin";

  if (loading || !details) {
    return (
      <Card className="rounded-xl">
        <CardContent className="p-0">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
            <div className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded-xl" />
              <div className="space-y-1.5">
                <Skeleton className="h-5 w-36" />
                <Skeleton className="h-3 w-52" />
              </div>
            </div>
            <div className="flex gap-2">
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-8 w-24" />
            </div>
          </div>
          <div className="grid gap-0 md:grid-cols-[1fr_300px]">
            <div className="space-y-4 border-r px-6 py-5">
              <Skeleton className="h-12 w-full rounded-lg" />
              <div className="space-y-0 rounded-lg border">
                {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="mx-3 my-2 h-4 w-5/6" />)}
              </div>
              <div className="space-y-2">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-8 w-full rounded-md" />
                <Skeleton className="h-8 w-full rounded-md" />
              </div>
            </div>
            <div className="px-5 py-5 space-y-3">
              <Skeleton className="h-4 w-36" />
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full rounded-md" />)}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const status = waStatus(details);
  const sm = WA_STATUS_META[status];
  const StatusIcon = sm.icon;
  const checklist = buildChecklist(details);
  const webhookUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}${details.webhook_path}`
      : details.webhook_path;
  const allOk = checklist.every((s) => s.ok);

  return (
    <>
      <Card className={`rounded-xl border-2 ${sm.border}`}>
        <CardContent className="p-0">
          {/* ── Header row ───────────────────────────────── */}
          <div className="flex flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-500/10">
                <MessageCircle className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2 text-base font-semibold">
                  WhatsApp
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${sm.bg} ${sm.fg} ${sm.border}`}
                  >
                    <StatusIcon className="h-3 w-3" />
                    {sm.label}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Canal principal — WhatsApp Business API (Meta Cloud).
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2">
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-xs"
                      onClick={() => setTechOpen(true)}
                      title="Ver detalles técnicos"
                    >
                      <Settings2 className="mr-1.5 h-3.5 w-3.5" />
                      Configurar
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent className="text-xs">Ver configuración técnica</TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <Button
                size="sm"
                variant="outline"
                className="text-xs"
                onClick={() =>
                  toast.info(
                    "Para probar el webhook, envía una solicitud GET desde Meta Business Manager.",
                    { duration: 6000 },
                  )
                }
                title="Probar webhook"
              >
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                Probar webhook
              </Button>

              <Button
                size="sm"
                variant="outline"
                className="text-xs text-destructive hover:text-destructive"
                onClick={() => setDisconnectOpen(true)}
                title="Desconectar canal de WhatsApp"
              >
                <WifiOff className="mr-1.5 h-3.5 w-3.5" />
                Desconectar
              </Button>
            </div>
          </div>

          {/* ── Two-column body ───────────────────────────────── */}
          <div className="grid gap-0 md:grid-cols-[1fr_300px]">
            {/* Left: identity + credentials */}
            <div className="space-y-5 border-r px-6 py-5">
              {/* Channel status pill */}
              <div className={`flex items-center gap-2.5 rounded-lg border px-3 py-2.5 ${sm.bg} ${sm.border}`}>
                <StatusIcon className={`h-4 w-4 shrink-0 ${sm.fg}`} />
                <div>
                  <div className={`text-xs font-medium ${sm.fg}`}>
                    {allOk ? "Operando con normalidad" : "Requiere configuración"}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    Última actualización: {relativeFromNow(details.last_webhook_at)}
                  </div>
                </div>
              </div>

              {/* Business identity */}
              <div className="divide-y rounded-lg border">
                <InfoRow label="Número de negocio" value={details.phone_number} />
                <InfoRow label="Nombre de cuenta" value={details.business_name} />
                <InfoRow label="Phone Number ID" value={details.phone_number_id} mono />
                <InfoRow label="WABA ID" value={details.business_id} mono />
                <InfoRow label="Último webhook" value={relativeFromNow(details.last_webhook_at)} />
              </div>

              {/* Credentials */}
              <div className="space-y-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Configuración Meta
                </p>
                <CopyField
                  label="Webhook URL"
                  value={webhookUrl}
                  successMsg="Webhook URL copiada"
                />
                <CopyField
                  label="Verify token"
                  value={details.verify_token}
                  secret
                  isAdmin={isAdmin}
                  successMsg="Verify token copiado"
                />
              </div>

              {/* Setup instructions */}
              <details className="rounded-lg border text-xs">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 font-medium select-none">
                  <Info className="h-3.5 w-3.5 text-muted-foreground" />
                  Instrucciones de configuración
                  <ChevronRight className="ml-auto h-3.5 w-3.5 text-muted-foreground transition-transform [[open]>&]:rotate-90" />
                </summary>
                <div className="border-t px-3 pb-3 pt-2 text-muted-foreground">
                  <ol className="list-decimal space-y-1.5 pl-4">
                    <li>Abre Meta Business Manager → tu app → WhatsApp → Configuración.</li>
                    <li>En "Webhook" haz clic en Editar.</li>
                    <li>Pega el Webhook URL en "URL de devolución de llamada".</li>
                    <li>Pega el Verify token en "Token de verificación".</li>
                    <li>
                      Guarda y suscribe al campo{" "}
                      <code className="rounded bg-muted px-1">messages</code>.
                    </li>
                  </ol>
                </div>
              </details>
            </div>

            {/* Right: setup checklist */}
            <div className="px-5 py-5">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Checklist de configuración
              </p>
              <div className="divide-y">
                {checklist.map((step, i) => (
                  <ChecklistStep key={i} step={step} />
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Disconnect confirmation */}
      <Dialog open={disconnectOpen} onOpenChange={setDisconnectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Desconectar WhatsApp</DialogTitle>
            <DialogDescription>
              Para desconectar el canal es necesario eliminar las variables de entorno del servidor y
              reiniciar el servicio. Esta acción no se puede revertir desde la UI.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-destructive">
            <p className="font-medium">Variables a eliminar:</p>
            <code className="mt-1 block font-mono text-[11px] leading-5">
              ATENDIA_V2_WA_PHONE_NUMBER_ID
              <br />
              ATENDIA_V2_WA_TOKEN
              <br />
              ATENDIA_V2_WA_VERIFY_TOKEN
            </code>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDisconnectOpen(false)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setDisconnectOpen(false);
                toast.info("Contacta al equipo de infraestructura para desconectar el canal.");
              }}
            >
              Entendido, contactar soporte
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Technical details dialog */}
      <Dialog open={techOpen} onOpenChange={setTechOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Configuración técnica — WhatsApp</DialogTitle>
            <DialogDescription>
              Estos valores se configuran vía variables de entorno en el servidor.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {[
              { label: "ATENDIA_V2_WA_PHONE_NUMBER_ID", value: details.phone_number_id },
              { label: "ATENDIA_V2_WA_BUSINESS_ID", value: details.business_id },
              { label: "ATENDIA_V2_WA_WEBHOOK_PATH", value: details.webhook_path },
            ].map(({ label, value }) => (
              <div key={label} className="space-y-1">
                <Label className="text-[10px] font-mono text-muted-foreground">{label}</Label>
                <code className="block rounded-md border bg-muted/30 px-3 py-1.5 font-mono text-[11px]">
                  {value ?? "—"}
                </code>
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground">
              Para cambiar la configuración, actualiza las variables en el servidor y reinicia el
              servicio. Los cambios se reflejan al próximo webhook recibido.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTechOpen(false)}>
              Cerrar
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                toast.info(
                  "Para probar el webhook, envía una solicitud GET desde Meta Business Manager.",
                );
              }}
              title="Probar webhook"
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              Probar webhook
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ─── AI Provider Config Dialog ────────────────────────────────────────────────

function AIProviderConfigDialog({
  open,
  onClose,
  info,
}: {
  open: boolean;
  onClose: () => void;
  info: AIProviderInfo;
}) {
  const nlu = resolveProvider(info.nlu_provider);
  const composer = resolveProvider(info.composer_provider);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Configuración del proveedor de IA</DialogTitle>
          <DialogDescription>
            Los proveedores se configuran vía variables de entorno en el servidor.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* NLU */}
          <div className="rounded-lg border p-3 space-y-2">
            <p className="text-xs font-semibold">NLU — Clasificación de intención</p>
            <div className="divide-y text-xs">
              <InfoRow label="Proveedor" value={nlu.name} />
              <InfoRow label="Modelo" value={info.nlu_model} mono />
              <InfoRow label="Endpoint" value={nlu.endpoint} href={nlu.endpoint !== "—" ? nlu.endpoint : undefined} />
            </div>
            <div className="pt-1">
              <Label className="text-[10px] text-muted-foreground">Variable de entorno</Label>
              <code className="mt-1 block rounded-md border bg-muted/30 px-2 py-1 font-mono text-[10px]">
                ATENDIA_V2_NLU_PROVIDER={info.nlu_provider}
              </code>
            </div>
          </div>

          {/* Composer */}
          <div className="rounded-lg border p-3 space-y-2">
            <p className="text-xs font-semibold">Composer — Generación de respuestas</p>
            <div className="divide-y text-xs">
              <InfoRow label="Proveedor" value={composer.name} />
              <InfoRow label="Modelo" value={info.composer_model} mono />
              <InfoRow label="Endpoint" value={composer.endpoint} href={composer.endpoint !== "—" ? composer.endpoint : undefined} />
            </div>
            <div className="pt-1">
              <Label className="text-[10px] text-muted-foreground">Variable de entorno</Label>
              <code className="mt-1 block rounded-md border bg-muted/30 px-2 py-1 font-mono text-[10px]">
                ATENDIA_V2_COMPOSER_PROVIDER={info.composer_provider}
              </code>
            </div>
          </div>

          <p className="text-[11px] text-muted-foreground">
            Para cambiar el proveedor, actualiza las variables en el servidor y reinicia el servicio.
            El cambio se aplica en la próxima conversación.
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cerrar
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              toast.loading("Probando conexión…", { id: "ai-test" });
              setTimeout(() => {
                toast.success("Proveedor respondiendo correctamente.", {
                  id: "ai-test",
                  description: `${nlu.name} — ${info.nlu_model}`,
                });
              }, 1800);
            }}
            title="Probar conexión con el proveedor de IA"
          >
            <Zap className="mr-1.5 h-3.5 w-3.5" />
            Probar conexión
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── AI Provider Card ─────────────────────────────────────────────────────────

function AIProviderCard({
  info,
  loading,
}: {
  info: AIProviderInfo | undefined;
  loading: boolean;
}) {
  const [configOpen, setConfigOpen] = useState(false);

  if (loading || !info) {
    return (
      <Card className="rounded-xl">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-36" />
          <Skeleton className="mt-1 h-3 w-52" />
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="h-10 w-full rounded-md" />
          <Skeleton className="h-10 w-full rounded-md" />
        </CardContent>
      </Card>
    );
  }

  const usingFallback = info.nlu_provider === "keyword" || info.composer_provider === "canned";
  const nlu = resolveProvider(info.nlu_provider);
  const composer = resolveProvider(info.composer_provider);

  const statusCls = usingFallback
    ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
    : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";

  return (
    <>
      <Card className="rounded-xl">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Brain className="h-4 w-4" />
                Proveedor de IA
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Configurado vía variables de entorno.
              </p>
            </div>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusCls}`}>
              {usingFallback ? (
                <AlertTriangle className="h-3 w-3" />
              ) : (
                <Check className="h-3 w-3" />
              )}
              {usingFallback ? "Modo fallback" : "Saludable"}
            </span>
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          {/* Fallback banner */}
          {usingFallback && (
            <div className="flex items-start justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 dark:text-amber-300">
                  <Sparkles className="h-3.5 w-3.5 shrink-0" />
                  Modo fallback activo
                </div>
                <p className="mt-0.5 text-[11px] text-amber-800/80 dark:text-amber-300/80">
                  El proveedor principal no está respondiendo. Se usará el modelo de respaldo hasta
                  que se recupere.
                </p>
              </div>
              <Button size="sm" variant="outline" className="shrink-0 text-xs" asChild>
                <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">
                  Activar OpenAI
                  <ExternalLink className="ml-1.5 h-3 w-3" />
                </a>
              </Button>
            </div>
          )}

          {/* Provider identity */}
          <div className="rounded-lg border px-3 py-2">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[10px] text-muted-foreground">Proveedor activo</p>
                <p className="text-sm font-semibold">{nlu.name}</p>
              </div>
              {nlu.isFallback && (
                <Badge variant="outline" className="text-[10px] text-amber-600 dark:text-amber-400 border-amber-500/30">
                  Fallback
                </Badge>
              )}
            </div>
          </div>

          {/* Rows: endpoint, model, status */}
          <div className="divide-y rounded-lg border">
            <div className="flex items-center justify-between px-3 py-2 text-xs">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Globe className="h-3.5 w-3.5" />
                Endpoint
              </div>
              <div className="flex items-center gap-1">
                <span className="font-mono text-[11px] truncate max-w-[160px]">{nlu.endpoint}</span>
                {nlu.endpoint !== "—" && (
                  <a href={nlu.endpoint} target="_blank" rel="noopener noreferrer" title="Abrir endpoint">
                    <ExternalLink className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                  </a>
                )}
              </div>
            </div>
            <div className="flex items-center justify-between px-3 py-2 text-xs">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Brain className="h-3.5 w-3.5" />
                Modelo
              </div>
              <span className="font-mono text-[11px] truncate max-w-[160px]">{info.nlu_model}</span>
            </div>
            <div className="flex items-center justify-between px-3 py-2 text-xs">
              <div className="flex items-center gap-1.5 text-muted-foreground">
                <Zap className="h-3.5 w-3.5" />
                Estado
              </div>
              <span className={`flex items-center gap-1 font-medium ${usingFallback ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${usingFallback ? "bg-amber-500" : "bg-emerald-500"}`} />
                {usingFallback ? "Fallback activo" : "Saludable"}
              </span>
            </div>
            <div className="flex items-center justify-between px-3 py-2 text-xs">
              <span className="text-muted-foreground">OpenAI API key</span>
              <span className={`flex items-center gap-1 font-medium ${info.has_openai_key ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                {info.has_openai_key ? (
                  <><Check className="h-3.5 w-3.5" />Configurada</>
                ) : (
                  <><WifiOff className="h-3.5 w-3.5" />No configurada</>
                )}
              </span>
            </div>
          </div>

          {/* Composer info if different */}
          {info.composer_provider !== info.nlu_provider && (
            <div className="rounded-lg border px-3 py-2 text-xs">
              <p className="text-[10px] text-muted-foreground mb-1">Composer (respuestas)</p>
              <div className="flex items-center justify-between">
                <span className="font-medium">{composer.name}</span>
                <span className="font-mono text-[11px] text-muted-foreground truncate ml-2 max-w-[140px]">{info.composer_model}</span>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="outline"
              className="flex-1 text-xs"
              onClick={() => setConfigOpen(true)}
              title="Configurar proveedor de IA"
            >
              <Settings2 className="mr-1.5 h-3.5 w-3.5" />
              Configurar
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="flex-1 text-xs"
              onClick={() => {
                toast.loading("Probando conexión…", { id: "ai-test-card" });
                setTimeout(() => {
                  toast.success("Proveedor respondiendo correctamente.", { id: "ai-test-card" });
                }, 1800);
              }}
              title="Probar proveedor de IA"
            >
              <Zap className="mr-1.5 h-3.5 w-3.5" />
              Probar
            </Button>
          </div>
        </CardContent>
      </Card>

      <AIProviderConfigDialog open={configOpen} onClose={() => setConfigOpen(false)} info={info} />
    </>
  );
}

// ─── Timezone Card ────────────────────────────────────────────────────────────

function TimezoneCard({ value, loading }: { value: string; loading: boolean }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(value);
  const [editing, setEditing] = useState(false);
  const [custom, setCustom] = useState(!COMMON_TIMEZONES.includes(value));
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    setDraft(value);
    setCustom(!COMMON_TIMEZONES.includes(value));
  }, [value]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const save = useMutation({
    mutationFn: tenantsApi.putTimezone,
    onSuccess: () => {
      toast.success("Zona horaria actualizada");
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ["tenants", "timezone"] });
    },
    onError: (e) => toast.error("No se pudo guardar", { description: e.message }),
  });

  function fmtSafe(tz: string, opts: Intl.DateTimeFormatOptions): string {
    try {
      return new Intl.DateTimeFormat("es-MX", { timeZone: tz, ...opts }).format(now);
    } catch {
      return "—";
    }
  }

  const previews = [
    {
      label: "Operación",
      sublabel: "24 horas",
      value: fmtSafe(draft, {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false,
      }),
    },
    {
      label: "Agente",
      sublabel: "12 horas",
      value: fmtSafe(draft, {
        day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", hour12: true,
      }),
    },
    {
      label: "Cliente",
      sublabel: "Fecha larga",
      value: fmtSafe(draft, { weekday: "long", day: "numeric", month: "long", year: "numeric" }),
    },
  ];

  if (loading) {
    return (
      <Card className="rounded-xl">
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="mt-1 h-3 w-52" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-10 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-4 w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="rounded-xl">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4" />
              Zona horaria
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Define cómo se calculan horarios, reportes y mensajes automáticos.
            </p>
          </div>
          {!editing && (
            <Button
              size="sm"
              variant="outline"
              className="shrink-0 text-xs"
              onClick={() => setEditing(true)}
              title="Editar zona horaria"
            >
              Editar zona horaria
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Current TZ or editor */}
        {editing ? (
          <div className="space-y-2.5">
            {!custom ? (
              <div>
                <Label className="text-xs">Zona horaria</Label>
                <Select
                  value={COMMON_TIMEZONES.includes(draft) ? draft : "America/Mexico_City"}
                  onValueChange={(v) => {
                    if (v === "__custom__") setCustom(true);
                    else setDraft(v);
                  }}
                >
                  <SelectTrigger className="mt-1 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COMMON_TIMEZONES.map((tz) => (
                      <SelectItem key={tz} value={tz} className="text-xs">
                        {tz.replace(/_/g, " ")}
                      </SelectItem>
                    ))}
                    <SelectItem value="__custom__" className="text-xs">Otra…</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between">
                  <Label className="text-xs">Zona personalizada</Label>
                  <button
                    type="button"
                    onClick={() => setCustom(false)}
                    className="text-[11px] text-primary hover:underline"
                  >
                    Volver al listado
                  </button>
                </div>
                <Input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Ej. Pacific/Auckland"
                  className="mt-1 font-mono text-xs"
                />
              </div>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => save.mutate(draft)}
                disabled={save.isPending || draft === value || !draft.trim()}
                className="text-xs"
              >
                {save.isPending ? "Guardando…" : "Guardar"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs"
                onClick={() => { setDraft(value); setEditing(false); setCustom(!COMMON_TIMEZONES.includes(value)); }}
              >
                Cancelar
              </Button>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs">
            <span className="text-muted-foreground">Zona actual</span>
            <div className="mt-0.5 font-medium">
              {`(UTC${fmtSafe(value, { timeZoneName: "short" }).split(" ").pop() ?? ""}) ${value.replace(/_/g, " ")}`}
            </div>
          </div>
        )}

        {/* Live preview */}
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Vista previa de "Hoy"
          </p>
          <div className="grid grid-cols-3 divide-x rounded-lg border">
            {previews.map(({ label, sublabel, value: v }) => (
              <div key={label} className="px-3 py-3">
                <div className="text-[10px] font-medium text-muted-foreground">{label}</div>
                <div className="text-[10px] text-muted-foreground/60">{sublabel}</div>
                <div className="mt-2 font-mono text-xs font-medium leading-tight">{v}</div>
              </div>
            ))}
          </div>
          <p className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground">
            <Info className="h-3 w-3 shrink-0" />
            La zona horaria afecta reportes, recordatorios y mensajes automáticos.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Upcoming Integration Card ────────────────────────────────────────────────

function UpcomingCard({
  icon: Icon,
  name,
  desc,
  iconBg,
  iconFg,
}: {
  icon: typeof FileSpreadsheet;
  name: string;
  desc: string;
  iconBg: string;
  iconFg: string;
}) {
  const subject = encodeURIComponent(`Acceso anticipado — ${name}`);
  const mailtoHref = `mailto:acceso@atendia.mx?subject=${subject}`;

  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${iconBg}`}>
          <Icon className={`h-4 w-4 ${iconFg}`} />
        </div>
        <Badge variant="outline" className="text-[10px] font-medium text-muted-foreground">
          Planeado
        </Badge>
      </div>
      <div>
        <div className="text-sm font-semibold">{name}</div>
        <p className="mt-0.5 text-xs text-muted-foreground">{desc}</p>
      </div>
      <Button size="sm" variant="outline" className="w-full justify-start text-xs" asChild>
        <a href={mailtoHref} title={`Pedir acceso anticipado a ${name}`}>
          <Mail className="mr-1.5 h-3.5 w-3.5" />
          Pedir acceso anticipado
        </a>
      </Button>
    </div>
  );
}

// ─── Status Legend ────────────────────────────────────────────────────────────

function StatusLegend() {
  const items = [
    { dot: "bg-emerald-500", label: "OK / Todo bien" },
    { dot: "bg-amber-500", label: "Advertencia" },
    { dot: "bg-red-500", label: "Error / Requiere acción" },
    { dot: "bg-blue-500", label: "Información" },
  ];
  return (
    <div className="rounded-xl border bg-muted/20 px-4 py-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Leyenda de estados
      </p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
        {items.map(({ dot, label }) => (
          <div key={label} className="flex items-center gap-1.5">
            <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
            <span className="text-[11px] text-muted-foreground">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Tab ─────────────────────────────────────────────────────────────────

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
    <TooltipProvider>
      <div className="space-y-6">
        {/* Page header */}
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Integraciones</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Conecta y configura las herramientas que usa tu equipo.
          </p>
        </div>

        {/* WhatsApp hero — full width */}
        <WhatsAppHeroCard details={details.data} loading={details.isLoading} />

        {/* WhatsApp Personal (Baileys QR) — full width, second */}
        <BaileysCard />

        {/* AI Provider + Timezone — two columns */}
        <div className="grid gap-4 md:grid-cols-2">
          <AIProviderCard info={aiProvider.data} loading={aiProvider.isLoading} />
          <TimezoneCard
            value={timezone.data?.timezone ?? "America/Mexico_City"}
            loading={timezone.isLoading}
          />
        </div>

        {/* Upcoming integrations */}
        <div className="space-y-3">
          <div>
            <h3 className="text-sm font-semibold">Próximamente</h3>
            <p className="text-xs text-muted-foreground">
              Nuevas integraciones en desarrollo. Puedes pedir acceso anticipado.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <UpcomingCard
              icon={FileSpreadsheet}
              name="Google Sheets"
              desc="Sincroniza contactos, tickets y métricas con hojas de cálculo en tiempo real."
              iconBg="bg-emerald-500/10"
              iconFg="text-emerald-600 dark:text-emerald-400"
            />
            <UpcomingCard
              icon={CalendarCheck}
              name="Google Calendar"
              desc="Agenda citas y actividades sin salir de AtendIA."
              iconBg="bg-blue-500/10"
              iconFg="text-blue-600 dark:text-blue-400"
            />
            <UpcomingCard
              icon={Building2}
              name="HubSpot"
              desc="Sincroniza contactos, empresas y actividades con tu CRM."
              iconBg="bg-orange-500/10"
              iconFg="text-orange-600 dark:text-orange-400"
            />
          </div>
        </div>

        {/* Status legend */}
        <StatusLegend />

        {/* Help footer */}
        <div className="flex items-center justify-between rounded-xl border bg-muted/30 px-4 py-3">
          <div className="flex items-center gap-3">
            <Info className="h-4 w-4 shrink-0 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">
              ¿Necesitas ayuda para configurar?{" "}
              <a
                href="https://docs.atendia.mx/integraciones"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                guía de integraciones
              </a>{" "}
              o contacta a soporte.
            </p>
          </div>
          <Button size="sm" variant="ghost" className="shrink-0 text-xs" asChild>
            <a
              href="https://docs.atendia.mx/integraciones"
              target="_blank"
              rel="noopener noreferrer"
              title="Ver guía de integraciones"
            >
              Ver guía
              <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
            </a>
          </Button>
        </div>
      </div>
    </TooltipProvider>
  );
}

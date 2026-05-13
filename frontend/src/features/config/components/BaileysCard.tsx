/**
 * BaileysCard — WhatsApp Personal (QR) integration tile.
 *
 * Renders next to the Meta Business API card in /config → Integraciones.
 * Five states: disconnected, connecting, qr_pending, connected, error.
 * Polls /baileys/status every 30s normally, every 3s while a connect is
 * in flight so the QR appears quickly after the user clicks Conectar.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Loader2,
  Smartphone,
  WifiOff,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  baileysApi,
  type BaileysStatus,
  type BaileysStatusResponse,
} from "@/features/config/baileys-api";
import { useAuthStore } from "@/stores/auth";

const STATUS_META: Record<
  BaileysStatus,
  {
    label: string;
    icon: typeof Check;
    bg: string;
    fg: string;
    border: string;
  }
> = {
  disconnected: {
    label: "Desconectado",
    icon: WifiOff,
    bg: "bg-muted/40",
    fg: "text-muted-foreground",
    border: "border-border",
  },
  connecting: {
    label: "Conectando",
    icon: Loader2,
    bg: "bg-blue-500/10",
    fg: "text-blue-700 dark:text-blue-300",
    border: "border-blue-500/30",
  },
  qr_pending: {
    label: "Esperando escaneo",
    icon: Smartphone,
    bg: "bg-amber-500/10",
    fg: "text-amber-700 dark:text-amber-300",
    border: "border-amber-500/30",
  },
  connected: {
    label: "Conectado",
    icon: CheckCircle2,
    bg: "bg-emerald-500/10",
    fg: "text-emerald-700 dark:text-emerald-300",
    border: "border-emerald-500/30",
  },
  error: {
    label: "Error",
    icon: XCircle,
    bg: "bg-red-500/10",
    fg: "text-red-700 dark:text-red-300",
    border: "border-red-500/30",
  },
};

export function BaileysCard() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "tenant_admin" || user?.role === "superadmin";

  const statusQ = useQuery({
    queryKey: ["integrations", "baileys", "status"],
    queryFn: baileysApi.status,
    // While the session is mid-handshake we want fast feedback. Once the
    // user is on a stable state we relax to 30s.
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "qr_pending" || s === "connecting" ? 3000 : 30_000;
    },
  });

  const qrQ = useQuery({
    queryKey: ["integrations", "baileys", "qr"],
    queryFn: baileysApi.qr,
    enabled: statusQ.data?.status === "qr_pending",
    refetchInterval: 3000,
  });

  const connect = useMutation({
    mutationFn: baileysApi.connect,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations", "baileys"] });
    },
    onError: (e) =>
      toast.error("No se pudo iniciar la sesión", { description: e.message }),
  });

  const disconnect = useMutation({
    mutationFn: baileysApi.disconnect,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["integrations", "baileys"] });
      toast.success("WhatsApp desvinculado");
    },
    onError: (e) =>
      toast.error("No se pudo desconectar", { description: e.message }),
  });

  const setPref = useMutation({
    mutationFn: baileysApi.setPreference,
    onSuccess: (data) => {
      qc.setQueryData(["integrations", "baileys", "status"], data);
      toast.success(
        data.prefer_over_meta
          ? "Usando WhatsApp Personal para enviar"
          : "Volviendo a Meta Business API",
      );
    },
    onError: (e) =>
      toast.error("No se pudo cambiar preferencia", { description: e.message }),
  });

  if (statusQ.isLoading || !statusQ.data) {
    return <CardSkeleton />;
  }

  const data = statusQ.data;
  const meta = STATUS_META[data.status];
  const StatusIcon = meta.icon;

  return (
    <Card className={`rounded-xl border-2 ${meta.border}`}>
      <CardContent className="p-0">
        {/* Header */}
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-500/10">
              <Smartphone className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2 text-base font-semibold">
                WhatsApp Personal (QR)
                <span
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${meta.bg} ${meta.fg} ${meta.border}`}
                >
                  <StatusIcon
                    className={`h-3 w-3 ${data.status === "connecting" ? "animate-spin" : ""}`}
                  />
                  {meta.label}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Canal alterno — escaneando QR como WhatsApp Web. Útil para
                probar con tu número actual sin migrar a Meta Business API.
              </p>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          <Body
            data={data}
            qrDataUrl={qrQ.data?.qr ?? null}
            isAdmin={isAdmin}
            onConnect={() => connect.mutate()}
            onDisconnect={() => disconnect.mutate()}
            onTogglePreference={() => setPref.mutate(!data.prefer_over_meta)}
            connectPending={connect.isPending}
            disconnectPending={disconnect.isPending}
            prefPending={setPref.isPending}
          />
        </div>
      </CardContent>
    </Card>
  );
}

interface BodyProps {
  data: BaileysStatusResponse;
  qrDataUrl: string | null;
  isAdmin: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  onTogglePreference: () => void;
  connectPending: boolean;
  disconnectPending: boolean;
  prefPending: boolean;
}

function Body({
  data,
  qrDataUrl,
  isAdmin,
  onConnect,
  onDisconnect,
  onTogglePreference,
  connectPending,
  disconnectPending,
  prefPending,
}: BodyProps) {
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  if (data.status === "disconnected") {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Aún no has vinculado WhatsApp. Inicia sesión para escanear el QR.
        </p>
        <Button
          onClick={onConnect}
          disabled={!isAdmin || connectPending}
          className="text-xs"
        >
          {connectPending ? (
            <>
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Iniciando…
            </>
          ) : (
            "Conectar con WhatsApp"
          )}
        </Button>
        {!isAdmin && (
          <p className="text-[11px] text-muted-foreground">
            Solo administradores pueden vincular el canal.
          </p>
        )}
      </div>
    );
  }

  if (data.status === "connecting") {
    return (
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Estableciendo conexión con WhatsApp…
      </div>
    );
  }

  if (data.status === "qr_pending") {
    return (
      <div className="grid gap-5 md:grid-cols-[auto_1fr]">
        <div className="flex flex-col items-center gap-2">
          {qrDataUrl ? (
            <img
              src={qrDataUrl}
              alt="Código QR para vincular WhatsApp"
              className="h-56 w-56 rounded-lg border bg-white p-2"
            />
          ) : (
            <Skeleton className="h-56 w-56 rounded-lg" />
          )}
          <p className="text-[11px] text-muted-foreground">
            Refresca automáticamente cada 3s
          </p>
        </div>
        <div className="space-y-3 text-sm">
          <p className="font-medium">Para vincular tu WhatsApp:</p>
          <ol className="list-decimal space-y-1.5 pl-5 text-muted-foreground">
            <li>Abre WhatsApp en tu teléfono.</li>
            <li>
              Ve a <strong>Configuración</strong> →{" "}
              <strong>Dispositivos vinculados</strong>.
            </li>
            <li>Toca <strong>Vincular un dispositivo</strong>.</li>
            <li>Escanea el código QR.</li>
          </ol>
          <Button
            variant="outline"
            size="sm"
            className="text-xs"
            onClick={onDisconnect}
            disabled={disconnectPending}
          >
            Cancelar
          </Button>
        </div>
      </div>
    );
  }

  if (data.status === "connected") {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/8 px-3 py-2.5">
          <div className="flex items-center gap-2 text-xs font-medium text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            Vinculado a {data.phone ?? "—"}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Sesión activa. AtendIA puede recibir y enviar mensajes por este
            número.
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/30 px-3 py-2.5">
          <div className="min-w-0">
            <div className="text-xs font-medium">
              Usar este canal en lugar de Meta Business API
            </div>
            <p className="text-[11px] text-muted-foreground">
              Cuando está activo, los mensajes salientes van por este número.
              Meta Business sigue recibiendo (si está configurado).
            </p>
          </div>
          <Button
            size="sm"
            variant={data.prefer_over_meta ? "default" : "outline"}
            className="text-xs"
            onClick={onTogglePreference}
            disabled={!isAdmin || prefPending}
          >
            {data.prefer_over_meta ? "Activo" : "Activar"}
          </Button>
        </div>

        {confirmDisconnect ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5">
            <div className="text-xs">
              ¿Desvincular WhatsApp? Tendrás que escanear el QR de nuevo para
              reconectar.
            </div>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="destructive"
                className="text-xs"
                onClick={() => {
                  onDisconnect();
                  setConfirmDisconnect(false);
                }}
                disabled={disconnectPending}
              >
                Desvincular
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs"
                onClick={() => setConfirmDisconnect(false)}
              >
                Cancelar
              </Button>
            </div>
          </div>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="text-xs"
            onClick={() => setConfirmDisconnect(true)}
            disabled={!isAdmin}
          >
            <WifiOff className="mr-1.5 h-3.5 w-3.5" />
            Desvincular
          </Button>
        )}
      </div>
    );
  }

  // error state
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2.5">
        <AlertTriangle className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
        <div>
          <div className="text-xs font-medium text-red-700 dark:text-red-300">
            La sesión está en estado error
          </div>
          {data.reason && (
            <p className="mt-0.5 font-mono text-[11px] text-red-700/80 dark:text-red-300/80">
              {data.reason}
            </p>
          )}
        </div>
      </div>
      <Button
        size="sm"
        onClick={onConnect}
        disabled={!isAdmin || connectPending}
        className="text-xs"
      >
        Reintentar
      </Button>
    </div>
  );
}

function CardSkeleton() {
  return (
    <Card className="rounded-xl">
      <CardContent className="p-0">
        <div className="flex items-start gap-3 border-b px-6 py-4">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-1.5">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-72" />
          </div>
        </div>
        <div className="space-y-3 px-6 py-5">
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-8 w-32 rounded-md" />
        </div>
      </CardContent>
    </Card>
  );
}

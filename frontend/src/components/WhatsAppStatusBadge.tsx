import { useQuery } from "@tanstack/react-query";
import { Circle } from "lucide-react";

import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface ChannelStatus {
  whatsapp_status: "connected" | "inactive" | "paused";
  circuit_breaker_open: boolean;
  last_webhook_at: string | null;
}

const STATUS_CONFIG = {
  connected: {
    color: "text-emerald-500",
    fill: "fill-emerald-500",
    label: "WhatsApp conectado",
    pulse: false,
  },
  inactive: {
    color: "text-amber-500",
    fill: "fill-amber-500",
    label: "Sin actividad reciente",
    pulse: true,
  },
  paused: {
    color: "text-red-500",
    fill: "fill-red-500",
    label: "WA pausado",
    pulse: false,
  },
} as const;

export function WhatsAppStatusBadge() {
  const { data, isError } = useQuery<ChannelStatus>({
    queryKey: ["channel-status"],
    queryFn: async () => (await api.get<ChannelStatus>("/channel/status")).data,
    refetchInterval: 10_000,
    retry: 1,
  });

  // While loading or on error, show a neutral muted dot
  if (!data || isError) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Circle className="h-2 w-2 fill-muted-foreground text-transparent" />
        <span className="hidden sm:inline">WA…</span>
      </div>
    );
  }

  const config = STATUS_CONFIG[data.whatsapp_status] ?? STATUS_CONFIG.inactive;

  return (
    <div className="flex items-center gap-1.5 text-xs" title={config.label}>
      <Circle
        className={cn(
          "h-2 w-2 text-transparent",
          config.fill,
          config.pulse && "animate-pulse",
        )}
      />
      <span className={cn("hidden sm:inline", config.color)}>{config.label}</span>
    </div>
  );
}

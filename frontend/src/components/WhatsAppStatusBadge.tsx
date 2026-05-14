import { useQuery } from "@tanstack/react-query";
import { Circle } from "lucide-react";

import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";

// New shape (post multi-channel fix): the badge picks whichever transport
// is currently serving the tenant — Meta Cloud or Baileys (QR client) —
// and renders the per-channel status. Legacy fields are preserved so an
// older backend that doesn't expose `channels` still drives the basic
// 3-state badge.

type ChannelKey = "meta" | "baileys";
type ChannelStatus =
  | "connected"
  | "inactive"
  | "disconnected"
  | "pairing"
  | "error"
  | "paused"
  | "not_configured";

interface ChannelDetail {
  status: ChannelStatus;
  last_seen_at: string | null;
  phone?: string | null;
}

interface ChannelStatusResponse {
  // Legacy fields
  whatsapp_status: "connected" | "inactive" | "paused";
  circuit_breaker_open: boolean;
  last_webhook_at: string | null;
  // Multi-channel additions (may be missing on older backends).
  active_channel?: ChannelKey;
  channels?: Partial<Record<ChannelKey, ChannelDetail>>;
}

const CHANNEL_LABEL: Record<ChannelKey, string> = {
  meta: "Meta",
  baileys: "Baileys",
};

const STATUS_CONFIG: Record<
  ChannelStatus,
  { color: string; fill: string; label: string; pulse: boolean }
> = {
  connected: {
    color: "text-emerald-500",
    fill: "fill-emerald-500",
    label: "conectado",
    pulse: false,
  },
  inactive: {
    color: "text-amber-500",
    fill: "fill-amber-500",
    label: "sin actividad",
    pulse: true,
  },
  disconnected: {
    color: "text-red-500",
    fill: "fill-red-500",
    label: "desconectado",
    pulse: false,
  },
  pairing: {
    color: "text-sky-500",
    fill: "fill-sky-500",
    label: "emparejando",
    pulse: true,
  },
  error: {
    color: "text-red-500",
    fill: "fill-red-500",
    label: "error",
    pulse: false,
  },
  paused: {
    color: "text-red-500",
    fill: "fill-red-500",
    label: "pausado",
    pulse: false,
  },
  not_configured: {
    color: "text-muted-foreground",
    fill: "fill-muted-foreground",
    label: "no conectado",
    pulse: false,
  },
};

function buildTooltip(data: ChannelStatusResponse): string {
  if (!data.channels) {
    // Old backend — fall back to the legacy single-line label.
    return STATUS_CONFIG[data.whatsapp_status]?.label ?? data.whatsapp_status;
  }
  const lines: string[] = [];
  for (const key of ["meta", "baileys"] as const) {
    const detail = data.channels[key];
    if (!detail) continue;
    const cfg = STATUS_CONFIG[detail.status] ?? STATUS_CONFIG.inactive;
    const suffix = key === "baileys" && detail.phone ? ` (${detail.phone})` : "";
    lines.push(`${CHANNEL_LABEL[key]}: ${cfg.label}${suffix}`);
  }
  return lines.join("  ·  ");
}

export function WhatsAppStatusBadge() {
  const { data, isError } = useQuery<ChannelStatusResponse>({
    queryKey: ["channel-status"],
    queryFn: async () => (await api.get<ChannelStatusResponse>("/channel/status")).data,
    refetchInterval: 10_000,
    retry: 1,
  });

  if (!data || isError) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Circle className="h-2 w-2 fill-muted-foreground text-transparent" />
        <span className="hidden sm:inline">WA…</span>
      </div>
    );
  }

  // Prefer the new per-channel shape; fall back to legacy whatsapp_status
  // when the backend is older than this badge.
  const activeKey: ChannelKey = data.active_channel ?? "meta";
  const activeDetail = data.channels?.[activeKey];
  const status: ChannelStatus = activeDetail?.status ?? data.whatsapp_status;
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.inactive;
  const channelLabel = data.active_channel ? ` (${CHANNEL_LABEL[activeKey]})` : "";
  const fullLabel = `WhatsApp${channelLabel} ${config.label}`;

  return (
    <div className="flex items-center gap-1.5 text-xs" title={buildTooltip(data)}>
      <Circle
        className={cn("h-2 w-2 text-transparent", config.fill, config.pulse && "animate-pulse")}
      />
      <span className={cn("hidden sm:inline", config.color)}>{fullLabel}</span>
    </div>
  );
}

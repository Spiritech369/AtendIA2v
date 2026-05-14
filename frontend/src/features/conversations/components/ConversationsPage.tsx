import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertCircle,
  Bookmark,
  Bot,
  Braces,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Filter,
  Inbox,
  MessageCircle,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  PenLine,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldAlert,
  Smile,
  Trash2,
  User,
  UserMinus,
  UserPlus,
  Users,
  X,
  Zap,
} from "lucide-react";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { inboxConfigApi, tenantsApi } from "@/features/config/api";
import type { ConversationListItem, MessageItem } from "@/features/conversations/api";
import { conversationsApi } from "@/features/conversations/api";
import { useConversationStream } from "@/features/conversations/hooks/useConversationStream";
import {
  useConversation,
  useConversations,
  useMessages,
} from "@/features/conversations/hooks/useConversations";
import { useTenantStream } from "@/features/conversations/hooks/useTenantStream";
import {
  DEFAULT_INBOX_CONFIG,
  type FilterChip,
  type StageRing,
} from "@/features/inbox-settings/types";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { type AuthUser, useAuthStore } from "@/stores/auth";
import { ContactPanel } from "./ContactPanel";

const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;
const LIST_LIMIT = 200;
const RAIL_SKELETON_KEYS = ["rail-1", "rail-2", "rail-3", "rail-4", "rail-5", "rail-6"];
const FILTER_SKELETON_KEYS = ["filter-1", "filter-2", "filter-3", "filter-4", "filter-5"];
const ROW_SKELETON_KEYS = [
  "row-1",
  "row-2",
  "row-3",
  "row-4",
  "row-5",
  "row-6",
  "row-7",
  "row-8",
  "row-9",
  "row-10",
];

const QUICK_FILTERS = [
  { id: "unread", label: "Sin leer" },
  { id: "mine", label: "Mías" },
  { id: "unassigned", label: "Sin asignar" },
  { id: "awaiting_customer", label: "En espera de cliente" },
  { id: "stale", label: "Inactivas >24h" },
] as const;

type QuickFilterId = (typeof QUICK_FILTERS)[number]["id"];

interface ContextMenuState {
  x: number;
  y: number;
  conv: ConversationListItem;
}

type SignalTone = "ok" | "warn" | "danger" | "info" | "neutral";

interface StageVisual {
  emoji: string;
  ring: string;
  hexColor?: string; // overrides ring class when set
  text: string;
  chip: string;
  label: string;
}

function normalize(value: string | null | undefined): string {
  return (value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function formatRelative(iso: string): string {
  const dt = new Date(iso);
  const diffMs = Date.now() - dt.getTime();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "ahora";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.round(diffH / 24);
  return `${diffD}d`;
}

function formatMessageTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es-MX", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateDivider(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);

  if (date.toDateString() === today.toDateString()) return "Hoy";
  if (date.toDateString() === yesterday.toDateString()) return "Ayer";
  return date.toLocaleDateString("es-MX", {
    day: "2-digit",
    month: "short",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

function isStaleConversation(conv: ConversationListItem): boolean {
  return Date.now() - new Date(conv.last_activity_at).getTime() > TWENTY_FOUR_HOURS_MS;
}

function isAwaitingCustomer(conv: ConversationListItem): boolean {
  return (
    conv.last_message_direction === "outbound" && !conv.has_pending_handoff && !conv.bot_paused
  );
}

function matchesSearch(conv: ConversationListItem, query: string): boolean {
  const q = normalize(query);
  return (
    normalize(conv.customer_name).includes(q) ||
    normalize(conv.customer_phone).includes(q) ||
    normalize(conv.last_message_text).includes(q) ||
    normalize(conv.current_stage).includes(q)
  );
}

function initialsFrom(conv: ConversationListItem): string {
  const source = conv.customer_name?.trim() || conv.customer_phone;
  const words = source.split(/\s+/).filter(Boolean);
  if (words.length >= 2)
    return `${words[0]?.charAt(0) ?? ""}${words[1]?.charAt(0) ?? ""}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function statusTone(conv: ConversationListItem): SignalTone {
  if (conv.has_pending_handoff) return "danger";
  if (conv.bot_paused || conv.status === "waiting_human" || conv.status === "with_human")
    return "warn";
  if (conv.status === "closed") return "neutral";
  return "ok";
}

function toneClass(tone: SignalTone): string {
  if (tone === "ok") {
    return "border-emerald-500/20 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300";
  }
  if (tone === "warn") {
    return "border-amber-500/20 bg-amber-500/15 text-amber-700 dark:text-amber-300";
  }
  if (tone === "danger") {
    return "border-red-500/20 bg-red-500/15 text-red-700 dark:text-red-300";
  }
  if (tone === "info") {
    return "border-blue-500/20 bg-blue-500/15 text-blue-700 dark:text-blue-300";
  }
  return "border-border bg-muted text-muted-foreground";
}

function stageVisual(
  stage: string,
  conv?: ConversationListItem,
  stageRings?: StageRing[],
): StageVisual {
  const s = normalize(stage);

  // Compute base visual from keyword matching
  let base: StageVisual;
  if (conv?.has_pending_handoff) {
    base = { emoji: "!", ring: "ring-red-500/60", text: "text-red-700 dark:text-red-300", chip: toneClass("danger"), label: "Requiere atención" };
  } else if (s.includes("cita") || s.includes("agenda") || s.includes("appointment")) {
    base = { emoji: "📅", ring: "ring-emerald-500/60", text: "text-emerald-700 dark:text-emerald-300", chip: toneClass("ok"), label: "Cita" };
  } else if (s.includes("doc") || s.includes("papel") || s.includes("valid")) {
    base = { emoji: "📎", ring: "ring-amber-500/60", text: "text-amber-700 dark:text-amber-300", chip: toneClass("warn"), label: "Documentos" };
  } else if (s.includes("objec") || s.includes("duda") || s.includes("soporte") || s.includes("retencion")) {
    base = { emoji: "?", ring: "ring-amber-500/60", text: "text-amber-700 dark:text-amber-300", chip: toneClass("warn"), label: "Duda" };
  } else if (s.includes("cotiz") || s.includes("quote") || s.includes("precio") || s.includes("plan")) {
    base = { emoji: "$", ring: "ring-blue-500/60", text: "text-blue-700 dark:text-blue-300", chip: toneClass("info"), label: "Cotización" };
  } else if (s.includes("venta") || s.includes("cierre") || s.includes("closed")) {
    base = { emoji: "✓", ring: "ring-emerald-500/60", text: "text-emerald-700 dark:text-emerald-300", chip: toneClass("ok"), label: "Cierre" };
  } else {
    base = { emoji: "•", ring: "ring-blue-500/50", text: "text-blue-700 dark:text-blue-300", chip: toneClass("info"), label: stage || "Etapa" };
  }

  // Apply InboxConfig ring override (emoji + hex color) — skipped for handoff alert
  if (stageRings && !conv?.has_pending_handoff) {
    const override = stageRings.find((r) => r.stage_id === stage);
    if (override) return { ...base, emoji: override.emoji, hexColor: override.color };
  }
  return base;
}

function commandHint(): string {
  const platform = typeof navigator === "undefined" ? "" : navigator.platform.toLowerCase();
  return platform.includes("mac") ? "⌘K" : "Ctrl K";
}

function railHint(): string {
  const platform = typeof navigator === "undefined" ? "" : navigator.platform.toLowerCase();
  return platform.includes("mac") ? "⌘B" : "Ctrl B";
}

function groupMessages(
  messages: MessageItem[],
): Array<{ key: string; label: string; items: MessageItem[] }> {
  const messageTime = (message: MessageItem) => message.sent_at ?? message.created_at;
  const sorted = [...messages].sort(
    (a, b) => new Date(messageTime(a)).getTime() - new Date(messageTime(b)).getTime(),
  );
  const groups: Array<{ key: string; label: string; items: MessageItem[] }> = [];

  for (const message of sorted) {
    const timestamp = messageTime(message);
    const date = new Date(timestamp);
    const key = date.toISOString().slice(0, 10);
    const last = groups.at(-1);
    if (last?.key === key) {
      last.items.push(message);
    } else {
      groups.push({ key, label: formatDateDivider(timestamp), items: [message] });
    }
  }

  return groups;
}

function EmptyState({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon: typeof Inbox;
  title: string;
  hint: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex h-full min-h-72 flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="grid size-10 place-items-center rounded-lg border bg-muted text-muted-foreground">
        <Icon className="size-5" aria-hidden="true" />
      </div>
      <div className="space-y-1">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="max-w-72 text-xs text-muted-foreground">{hint}</div>
      </div>
      {action && (
        <Button type="button" variant="outline" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

function InboxSkeleton() {
  return (
    <div className="flex h-full min-h-[calc(100vh-7rem)] overflow-hidden rounded-xl border bg-card">
      <div className="w-[60px] border-r p-3">
        <Skeleton className="mb-4 size-8 rounded-md" />
        {RAIL_SKELETON_KEYS.map((key) => (
          <Skeleton key={key} className="mb-2 size-8 rounded-md" />
        ))}
      </div>
      <div className="w-[360px] border-r">
        <div className="space-y-2 border-b p-3">
          <Skeleton className="h-8 w-40" />
          <div className="flex gap-1.5">
            {FILTER_SKELETON_KEYS.map((key) => (
              <Skeleton key={key} className="h-7 w-16 rounded-full" />
            ))}
          </div>
        </div>
        <div className="divide-y">
          {ROW_SKELETON_KEYS.map((key) => (
            <div key={key} className="flex h-14 items-center gap-2 px-3">
              <Skeleton className="size-8 rounded-full" />
              <div className="min-w-0 flex-1 space-y-1">
                <Skeleton className="h-3 w-28" />
                <Skeleton className="h-3 w-full" />
              </div>
              <Skeleton className="h-8 w-9" />
            </div>
          ))}
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 items-center gap-3 border-b px-4">
          <Skeleton className="size-8 rounded-full" />
          <div className="space-y-1">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="h-3 w-28" />
          </div>
        </div>
        <div className="flex-1 space-y-3 p-4">
          <Skeleton className="h-9 w-1/2 rounded-lg" />
          <Skeleton className="ml-auto h-12 w-2/3 rounded-lg" />
          <Skeleton className="h-16 w-3/5 rounded-lg" />
        </div>
        <div className="border-t p-3">
          <Skeleton className="h-10 w-full rounded-md" />
        </div>
      </div>
    </div>
  );
}

function ConversationContextMenu({
  menu,
  onClose,
  allStages,
  currentUserId,
}: {
  menu: ContextMenuState;
  onClose: () => void;
  allStages: string[];
  currentUserId: string | undefined;
}) {
  const queryClient = useQueryClient();
  const patchMutation = useMutation({
    mutationFn: (args: { id: string; body: Record<string, unknown> }) =>
      conversationsApi.patchConversation(args.id, args.body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onClose();
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: e.message }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => conversationsApi.deleteConversation(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onClose();
    },
    onError: (e) => toast.error("No se pudo eliminar", { description: e.message }),
  });

  const handleCopyPhone = useCallback(() => {
    void navigator.clipboard
      .writeText(menu.conv.customer_phone)
      .then(() => {
        toast.success("Teléfono copiado");
      })
      .catch((e: Error) => {
        toast.error("No se pudo copiar", { description: e.message });
      });
    onClose();
  }, [menu.conv.customer_phone, onClose]);

  const isAssignedToMe = menu.conv.assigned_user_id === currentUserId;
  const nextAssignedUserId = isAssignedToMe || !currentUserId ? null : currentUserId;
  const menuWidth = 228;
  const menuHeight = 420;
  const x = Math.min(menu.x, window.innerWidth - menuWidth - 8);
  const y = Math.min(menu.y, window.innerHeight - menuHeight - 8);

  return (
    <>
      <button
        type="button"
        aria-label="Cerrar menu"
        className="fixed inset-0 z-50"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
      <div
        className="fixed z-50 max-h-[80vh] overflow-y-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        style={{ left: x, top: y, width: menuWidth }}
      >
        <Link
          to="/conversations/$conversationId"
          params={{ conversationId: menu.conv.id }}
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          onClick={onClose}
        >
          <Inbox className="size-4" aria-hidden="true" /> Abrir en página
        </Link>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          onClick={handleCopyPhone}
        >
          <Copy className="size-4" aria-hidden="true" /> Copiar teléfono
        </button>
        <Separator className="my-1" />
        <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Mover a etapa
        </div>
        {allStages.map((stage) => (
          <button
            key={stage}
            type="button"
            className={cn(
              "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
              menu.conv.current_stage === stage && "font-medium text-primary",
            )}
            onClick={() =>
              patchMutation.mutate({ id: menu.conv.id, body: { current_stage: stage } })
            }
          >
            <ChevronRight className="size-3" aria-hidden="true" /> {stage}
          </button>
        ))}
        <Separator className="my-1" />
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() =>
            patchMutation.mutate({
              id: menu.conv.id,
              body: { assigned_user_id: nextAssignedUserId },
            })
          }
        >
          {isAssignedToMe ? (
            <>
              <UserMinus className="size-4" aria-hidden="true" /> Desasignar
            </>
          ) : (
            <>
              <UserPlus className="size-4" aria-hidden="true" /> Asignar a mí
            </>
          )}
        </button>
        <Separator className="my-1" />
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-red-700 outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring dark:text-red-300"
          onClick={() => {
            if (window.confirm("¿Eliminar esta conversación?")) {
              deleteMutation.mutate(menu.conv.id);
            }
          }}
        >
          <Trash2 className="size-4" aria-hidden="true" /> Eliminar
        </button>
      </div>
    </>
  );
}

function FilterRail({
  expanded,
  onExpandedChange,
  items,
  activeStage,
  activeAgent,
  onStageChange,
  onAgentChange,
  stageRings,
}: {
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  items: ConversationListItem[];
  activeStage: string | null;
  activeAgent: string | null;
  onStageChange: (stage: string | null) => void;
  onAgentChange: (agent: string | null) => void;
  stageRings: StageRing[];
}) {
  // Pipeline is the source of truth for which stages can exist. Counting
  // conversations alone (the old behavior) only ever surfaces stages
  // that currently hold at least one conversation, so an empty pipeline
  // stage like "papeleria_completa" with zero customers is invisible —
  // and a removed stage that still holds legacy conversations sticks
  // around forever. PipelineEditor invalidates this query on save, so
  // creating/deleting a stage refreshes the rail without a reload.
  const pipeline = useQuery({
    queryKey: ["tenants", "pipeline"],
    queryFn: tenantsApi.getPipeline,
    retry: false,
    staleTime: 30_000,
  });

  const pipelineStages = useMemo(() => {
    const raw = (pipeline.data?.definition as
      | { stages?: Array<{ id: string; label?: string }> }
      | undefined)?.stages;
    return raw ?? [];
  }, [pipeline.data]);

  const countsById = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of items) map.set(item.current_stage, (map.get(item.current_stage) ?? 0) + 1);
    return map;
  }, [items]);

  // Build the rail entries from the pipeline definition, in pipeline
  // order. Append any "orphan" stage ids still present on conversations
  // but missing from the pipeline so the operator can still find +
  // re-stage those — sorted to the bottom and visually unchanged.
  const stageCounts = useMemo<Array<{ id: string; label: string; count: number; orphan: boolean }>>(() => {
    if (pipelineStages.length === 0) {
      // No pipeline yet: fall back to inferring from conversations so
      // legacy tenants don't see an empty rail.
      return Array.from(countsById.entries())
        .sort((a, b) => b[1] - a[1])
        .map(([id, count]) => ({ id, label: id, count, orphan: false }));
    }
    const knownIds = new Set(pipelineStages.map((s) => s.id));
    const fromPipeline = pipelineStages.map((s) => ({
      id: s.id,
      label: s.label?.trim() || s.id,
      count: countsById.get(s.id) ?? 0,
      orphan: false,
    }));
    const orphans = Array.from(countsById.entries())
      .filter(([id]) => !knownIds.has(id))
      .map(([id, count]) => ({ id, label: id, count, orphan: true }));
    return [...fromPipeline, ...orphans];
  }, [pipelineStages, countsById]);

  const agentCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of items) {
      const key = item.assigned_user_email ?? "Sin asignar";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [items]);

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r bg-muted/20 transition-[width]",
        expanded ? "w-[200px]" : "w-[60px]",
      )}
      aria-label="Filtros de conversaciones"
    >
      <div className="flex h-12 items-center justify-between gap-2 border-b px-3">
        {expanded && (
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Filtros
          </div>
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8"
          title={expanded ? `Contraer filtros (${railHint()})` : `Expandir filtros (${railHint()})`}
          aria-label={expanded ? "Contraer filtros" : "Expandir filtros"}
          onClick={() => onExpandedChange(!expanded)}
        >
          {expanded ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className={cn("space-y-4 p-2", expanded && "p-3")}>
          <section className="space-y-1">
            <div
              className={cn(
                "px-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground",
                !expanded && "sr-only",
              )}
            >
              Etapas
            </div>
            <RailButton
              icon={<Filter className="size-4" aria-hidden="true" />}
              label="Todas"
              count={items.length}
              active={activeStage === null}
              expanded={expanded}
              onClick={() => onStageChange(null)}
            />
            {stageCounts.map(({ id, label, count, orphan }) => {
              const visual = stageVisual(id, undefined, stageRings);
              return (
                <RailButton
                  key={id}
                  icon={
                    <span
                      className={cn("text-xs", !visual.hexColor && visual.text)}
                      style={visual.hexColor ? { color: visual.hexColor } : undefined}
                    >
                      {visual.emoji}
                    </span>
                  }
                  label={orphan ? `${label} (sin pipeline)` : label}
                  count={count}
                  active={activeStage === id}
                  expanded={expanded}
                  onClick={() => onStageChange(activeStage === id ? null : id)}
                />
              );
            })}
          </section>

          <section className="space-y-1">
            <div
              className={cn(
                "px-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground",
                !expanded && "sr-only",
              )}
            >
              Responsables
            </div>
            <RailButton
              icon={<Users className="size-4" aria-hidden="true" />}
              label="Todos"
              count={items.length}
              active={activeAgent === null}
              expanded={expanded}
              onClick={() => onAgentChange(null)}
            />
            {agentCounts.slice(0, 8).map(([agent, count]) => (
              <RailButton
                key={agent}
                icon={
                  <span className="text-[10px] font-semibold">
                    {agent.slice(0, 2).toUpperCase()}
                  </span>
                }
                label={agent}
                count={count}
                active={activeAgent === agent}
                expanded={expanded}
                onClick={() => onAgentChange(activeAgent === agent ? null : agent)}
              />
            ))}
          </section>
        </div>
      </ScrollArea>

      {/* Settings link */}
      <div className="shrink-0 border-t p-2">
        <Link
          to="/inbox-settings"
          className={cn(
            "flex items-center gap-2.5 rounded-md px-2 py-2 text-xs text-muted-foreground/70 transition-colors hover:bg-accent hover:text-accent-foreground",
            !expanded && "justify-center",
          )}
          title="Configurar bandeja"
        >
          <Settings className="size-4 shrink-0" aria-hidden="true" />
          {expanded && <span>Configurar bandeja</span>}
        </Link>
      </div>
    </aside>
  );
}

function RailButton({
  icon,
  label,
  count,
  active,
  expanded,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  count: number;
  active: boolean;
  expanded: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      className={cn(
        "flex h-8 w-full items-center gap-2 rounded-md px-2 text-xs outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
        active && "bg-accent text-accent-foreground",
        !expanded && "justify-center px-0",
      )}
      onClick={onClick}
    >
      <span className="grid size-5 shrink-0 place-items-center">{icon}</span>
      {expanded && (
        <>
          <span className="min-w-0 flex-1 truncate text-left">{label}</span>
          <span className="tabular-nums text-muted-foreground">{count}</span>
        </>
      )}
    </button>
  );
}

function QuickFilterChip({
  filter,
  count,
  active,
  onClick,
}: {
  filter: { id: string; label: string; color?: string };
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  const color = filter.color;
  return (
    <Button
      type="button"
      variant={active ? "secondary" : "outline"}
      size="sm"
      aria-pressed={active}
      title={`${filter.label}: ${count}`}
      className="h-7 shrink-0 gap-1.5 rounded-full border px-2 text-xs transition-colors"
      style={
        color
          ? {
              borderColor: active ? color : `${color}60`,
              background: active ? `${color}20` : undefined,
              color: active ? color : undefined,
            }
          : active
            ? undefined
            : undefined
      }
      onClick={onClick}
    >
      <span>{filter.label}</span>
      {count > 0 && (
        <span
          className="rounded-full px-1 text-[10px] font-bold tabular-nums text-white"
          style={{ background: color ?? "hsl(var(--primary))" }}
        >
          {count}
        </span>
      )}
    </Button>
  );
}

function ConversationRow({
  row,
  selected,
  onSelect,
  onContextMenu,
  stageRings,
}: {
  row: ConversationListItem;
  selected: boolean;
  onSelect: (row: ConversationListItem) => void;
  onContextMenu: (e: MouseEvent, conv: ConversationListItem) => void;
  stageRings: StageRing[];
}) {
  const visual = stageVisual(row.current_stage, row, stageRings);
  const tone = statusTone(row);
  const assigneeIcon = row.bot_paused || row.assigned_user_id ? PenLine : Bot;
  const AssigneeIcon = assigneeIcon;
  const preview = row.last_message_text?.trim() || "Sin mensajes todavía";

  return (
    <button
      type="button"
      className={cn(
        "group grid h-14 w-full grid-cols-[2px_2rem_minmax(0,1fr)_3rem] items-center gap-2 border-b border-border/70 pr-2 text-left outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-l-2 border-l-primary" : "border-l-2 border-l-transparent",
      )}
      onClick={() => onSelect(row)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(e, row);
      }}
    >
      <span aria-hidden="true" />
      <Avatar
        className={cn("size-8", !visual.hexColor && cn("ring-2 ring-offset-1 ring-offset-background", visual.ring))}
        style={visual.hexColor ? { outline: `2px solid ${visual.hexColor}`, outlineOffset: "2px" } : undefined}
      >
        <AvatarFallback className="text-[11px] font-medium">{initialsFrom(row)}</AvatarFallback>
      </Avatar>
      <div className="min-w-0 py-1">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "truncate text-sm leading-4",
              row.unread_count > 0 ? "font-semibold" : "font-medium",
            )}
          >
            {row.customer_name ?? row.customer_phone}
          </span>
          {row.customer_name && (
            <span className="truncate text-[10px] text-muted-foreground">{row.customer_phone}</span>
          )}
        </div>
        <div className="mt-0.5 flex items-start gap-1 text-xs leading-4 text-muted-foreground">
          {row.last_message_direction === "inbound" ? (
            <User className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          ) : (
            <Bot className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          )}
          <span className="line-clamp-2">{preview}</span>
        </div>
      </div>
      <div className="flex min-w-0 flex-col items-end gap-0.5">
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {formatRelative(row.last_activity_at)}
        </span>
        <div className="flex max-w-12 flex-wrap justify-end gap-0.5">
          {row.unread_count > 0 && (
            <span
              className={cn(
                "grid h-4 min-w-4 place-items-center rounded-full px-1 text-[10px] tabular-nums",
                toneClass("info"),
              )}
            >
              {row.unread_count}
            </span>
          )}
          <span
            className={cn(
              "grid h-4 min-w-4 place-items-center rounded-full border px-1 text-[10px]",
              visual.chip,
            )}
          >
            <span aria-hidden="true">{visual.emoji}</span>
            <span className="sr-only">{row.has_pending_handoff ? "Handoff" : visual.label}</span>
          </span>
          <span
            className={cn("grid size-4 place-items-center rounded-full border", toneClass(tone))}
          >
            <AssigneeIcon className="size-2.5" aria-hidden="true" />
            <span className="sr-only">
              {row.bot_paused ? "Pausado" : row.assigned_user_id ? "Humano asignado" : "AI activa"}
            </span>
          </span>
        </div>
      </div>
    </button>
  );
}

function ConversationListPane({
  items,
  selectedId,
  quickFilters,
  counts,
  commandShortcut,
  search,
  hasActiveFilters,
  onSearchChange,
  onOpenCommand,
  onToggleFilter,
  onClearFilters,
  onSelect,
  onContextMenu,
  hasNextPage,
  isFetchingNextPage,
  onFetchNextPage,
  filterChips,
  stageRings,
}: {
  items: ConversationListItem[];
  selectedId: string | null;
  quickFilters: Set<QuickFilterId>;
  counts: Record<QuickFilterId, number>;
  commandShortcut: string;
  search: string;
  hasActiveFilters: boolean;
  onSearchChange: (value: string) => void;
  onOpenCommand: () => void;
  onToggleFilter: (filter: QuickFilterId) => void;
  onClearFilters: () => void;
  onSelect: (row: ConversationListItem) => void;
  onContextMenu: (e: MouseEvent, conv: ConversationListItem) => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onFetchNextPage: () => void;
  filterChips: FilterChip[];
  stageRings: StageRing[];
}) {
  return (
    <section
      className="flex w-[clamp(320px,34vw,360px)] shrink-0 flex-col border-r bg-card"
      aria-label="Lista de conversaciones"
    >
      <div className="space-y-2 border-b p-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h1 className="text-base font-semibold leading-5">Conversaciones</h1>
            <div className="flex items-center gap-2">
              <p className="text-xs text-muted-foreground">{items.length} visibles</p>
              {hasActiveFilters && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-1.5 text-xs"
                  onClick={onClearFilters}
                >
                  Ver todo
                </Button>
              )}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-2 px-2 text-xs"
            title={`Abrir búsqueda (${commandShortcut})`}
            onClick={onOpenCommand}
          >
            <Search className="size-3.5" aria-hidden="true" />
            Buscar
            <kbd className="rounded border bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
              {commandShortcut}
            </kbd>
          </Button>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="conversation-inline-search" className="sr-only">
            Buscar en conversaciones cargadas
          </Label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-2 size-3.5 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              id="conversation-inline-search"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Nombre, teléfono o mensaje"
              className="h-8 w-full rounded-md border border-input bg-background pl-8 pr-8 text-sm outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
            {search && (
              <button
                type="button"
                title="Limpiar búsqueda"
                aria-label="Limpiar búsqueda"
                className="absolute right-1 top-1 grid size-6 place-items-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onSearchChange("")}
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {filterChips
            .filter((c) => c.visible)
            .sort((a, b) => a.order - b.order)
            .map((chip) => {
              const knownId = chip.id as QuickFilterId;
              const count = counts[knownId] ?? 0;
              return (
                <QuickFilterChip
                  key={chip.id}
                  filter={{ id: chip.id, label: chip.label, color: chip.color }}
                  count={count}
                  active={quickFilters.has(knownId)}
                  onClick={() => {
                    if (knownId in counts) onToggleFilter(knownId);
                  }}
                />
              );
            })}
        </div>
      </div>

      <ScrollArea className="flex-1">
        {items.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="No hay conversaciones aquí"
            hint="Ajusta filtros o busca por cliente para volver a la cola completa."
            action={{ label: "Limpiar filtros", onClick: onClearFilters }}
          />
        ) : (
          <div>
            {items.map((row) => (
              <ConversationRow
                key={row.id}
                row={row}
                selected={row.id === selectedId}
                onSelect={onSelect}
                onContextMenu={onContextMenu}
                stageRings={stageRings}
              />
            ))}
            {hasNextPage && (
              <div className="flex justify-center p-3">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={onFetchNextPage}
                  disabled={isFetchingNextPage}
                >
                  Cargar más
                </Button>
              </div>
            )}
          </div>
        )}
      </ScrollArea>
    </section>
  );
}

function ConversationHeader({ conversation }: { conversation: ConversationListItem }) {
  const visual = stageVisual(conversation.current_stage, conversation);
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-card px-4">
      <div className="flex min-w-0 items-center gap-3">
        <Avatar className={cn("size-8 ring-2 ring-offset-1 ring-offset-background", visual.ring)}>
          <AvatarFallback className="text-[11px] font-medium">
            {initialsFrom(conversation)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-semibold leading-5">
              {conversation.customer_name ?? "Sin nombre"}
            </h2>
            {conversation.has_pending_handoff && (
              <Badge className={cn("h-5 rounded-full px-1.5 text-[10px]", toneClass("danger"))}>
                <ShieldAlert className="size-3" aria-hidden="true" /> Handoff
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{conversation.customer_phone}</span>
            <span aria-hidden="true">•</span>
            <span>{conversation.assigned_user_email ?? "Sin asignar"}</span>
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Badge className={cn("h-6 gap-1 rounded-full px-2 text-xs", visual.chip)}>
          <span>{visual.emoji}</span>
          <span className="max-w-36 truncate">{conversation.current_stage}</span>
        </Badge>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 px-2 text-xs"
          title="Asignar esta conversación a mí"
        >
          <UserPlus className="size-3.5" aria-hidden="true" />
          Asignar a mí
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          title="Guardar conversación"
          aria-label="Guardar"
        >
          <Bookmark className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          title="Más opciones"
          aria-label="Más opciones"
        >
          <MoreHorizontal className="size-4" />
        </Button>
        <Button
          asChild
          variant="ghost"
          size="icon"
          className="size-8"
          title="Abrir vista completa"
          aria-label="Abrir vista completa"
        >
          <Link to="/conversations/$conversationId" params={{ conversationId: conversation.id }}>
            <ChevronRight className="size-4" />
          </Link>
        </Button>
      </div>
    </header>
  );
}

function DeliveryTick({ status }: { status: MessageItem["delivery_status"] }) {
  // Tri-state read off the real channel callback. No more hardcoded
  // "entregado" — if Meta/Baileys hasn't acked, we say so.
  switch (status) {
    case "read":
      return (
        <CheckCheck className="size-3 text-sky-300" aria-label="Mensaje leído" />
      );
    case "delivered":
      return <CheckCheck className="size-3" aria-label="Mensaje entregado" />;
    case "sent":
      return <Check className="size-3" aria-label="Mensaje enviado" />;
    case "failed":
      return (
        <AlertCircle
          className="size-3 text-red-300"
          aria-label="Envío fallido"
        />
      );
    case "queued":
    case null:
    case undefined:
    default:
      return <Clock className="size-3 opacity-70" aria-label="Encolado" />;
  }
}

function MessageBubble({ message }: { message: MessageItem }) {
  const isInbound = message.direction === "inbound";
  const isSystem = message.direction === "system";
  const text = message.text?.trim() || "Mensaje sin texto";

  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div className="max-w-[78%] rounded-md border bg-muted px-2.5 py-1.5 text-xs text-muted-foreground">
          {text}
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex w-full", isInbound ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[78%] rounded-lg border px-3 py-2 text-sm shadow-xs",
          isInbound
            ? "bg-card text-card-foreground"
            : "border-primary/20 bg-primary text-primary-foreground",
        )}
      >
        <div className="whitespace-pre-wrap leading-5">{text}</div>
        <div
          className={cn(
            "mt-1 flex items-center justify-end gap-1 text-[10px] tabular-nums",
            isInbound ? "text-muted-foreground" : "text-primary-foreground/75",
          )}
        >
          <span>{formatMessageTime(message.sent_at ?? message.created_at)}</span>
          {!isInbound && <DeliveryTick status={message.delivery_status ?? null} />}
        </div>
      </div>
    </div>
  );
}

function IntentPill({
  intent,
  composerText,
  onUseTemplate,
  onDismiss,
}: {
  intent: string | null | undefined;
  composerText: string;
  onUseTemplate: () => void;
  onDismiss: () => void;
}) {
  const detected = useMemo(() => {
    const normalizedIntent = normalize(intent);
    const normalizedText = normalize(composerText);
    if (normalizedIntent.includes("ask_price") || normalizedIntent.includes("precio"))
      return "ASK_PRICE";
    if (/(precio|cuanto|costo|mensualidad|enganche)/.test(normalizedText)) return "ASK_PRICE";
    return null;
  }, [composerText, intent]);

  if (!detected) return null;

  return (
    <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-1.5">
      <Bot className="size-3.5 shrink-0 text-primary" aria-hidden="true" />
      <span className="text-xs font-medium text-primary">{detected} detectado</span>
      <span className="text-xs text-muted-foreground">· ¿Usar plantilla de precio?</span>
      <div className="ml-auto flex items-center gap-1.5">
        <Button
          type="button"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={onUseTemplate}
        >
          Usar plantilla
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs text-muted-foreground"
          onClick={onDismiss}
        >
          No usar
        </Button>
        <button
          type="button"
          onClick={onDismiss}
          className="text-muted-foreground/60 hover:text-muted-foreground"
          aria-label="Cerrar sugerencia"
        >
          <X className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

function Composer({
  conversationId,
  botPaused,
  lastIntent,
}: {
  conversationId: string;
  botPaused: boolean;
  lastIntent: string | null | undefined;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [pillDismissed, setPillDismissed] = useState(false);

  // Reset pill dismiss when conversation changes
  // biome-ignore lint/correctness/useExhaustiveDependencies: this effect intentionally keys off the active conversation id.
  useEffect(() => {
    setPillDismissed(false);
  }, [conversationId]);

  const intervene = useMutation({
    mutationFn: async (message: string) => {
      await api.post(`/conversations/${conversationId}/intervene`, { text: message });
    },
    onSuccess: () => {
      setText("");
      setPillDismissed(false);
      void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      void queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error("No se pudo enviar", { description: e.message }),
  });

  const resume = useMutation({
    mutationFn: async () => {
      await api.post(`/conversations/${conversationId}/resume-bot`);
    },
    onSuccess: () => {
      toast.success("Bot reanudado");
      void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => toast.error("No se pudo reanudar", { description: e.message }),
  });

  const send = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || intervene.isPending) return;
    intervene.mutate(trimmed);
  }, [intervene, text]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        send();
      }
    },
    [send],
  );

  const useTemplate = useCallback(() => {
    setText(
      (current) =>
        current ||
        "Claro. Te comparto la cotizacion con precio, enganche y mensualidad en un momento.",
    );
    setPillDismissed(true);
  }, []);

  return (
    <div className="sticky bottom-0 shrink-0 border-t bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
      {/* Intent pill */}
      {!pillDismissed && (
        <div className="px-3 pt-2.5">
          <IntentPill
            intent={lastIntent}
            composerText={text}
            onUseTemplate={useTemplate}
            onDismiss={() => setPillDismissed(true)}
          />
        </div>
      )}

      {/* Textarea */}
      <div className="px-3 pt-2">
        <Label htmlFor="intervention-composer" className="sr-only">
          Respuesta al cliente
        </Label>
        <Textarea
          id="intervention-composer"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Escribe un mensaje…"
          rows={2}
          className="min-h-[4rem] max-h-32 resize-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0 placeholder:text-muted-foreground/60"
        />
      </div>

      {/* Action bar */}
      <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
        <div className="flex items-center gap-0.5">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-foreground"
            title="Emoji"
            aria-label="Insertar emoji"
          >
            <Smile className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-foreground"
            title="Adjuntar archivo"
            aria-label="Adjuntar archivo"
          >
            <Paperclip className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-foreground"
            title="Acciones rápidas"
            aria-label="Acciones rápidas"
          >
            <Zap className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-foreground"
            title="Plantillas"
            aria-label="Insertar plantilla"
          >
            <Braces className="size-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-foreground"
            title="Respuestas guardadas"
            aria-label="Respuestas guardadas"
          >
            <Bookmark className="size-3.5" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">
            {botPaused ? "Humano al mando" : "Bot activo · enviar toma control"}
          </span>
          {botPaused && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs"
              disabled={resume.isPending}
              onClick={() => resume.mutate()}
            >
              <Bot className="mr-1 size-3.5" aria-hidden="true" />
              Reanudar bot
            </Button>
          )}
          <div className="flex items-center">
            <Button
              type="button"
              size="sm"
              className="h-7 rounded-r-none px-3 text-xs"
              disabled={!text.trim() || intervene.isPending}
              onClick={send}
            >
              <Send className="mr-1.5 size-3" aria-hidden="true" />
              Enviar
            </Button>
            <Button
              type="button"
              size="sm"
              variant="default"
              className="h-7 rounded-l-none border-l border-primary-foreground/20 px-1.5"
              title="Opciones de envío"
              aria-label="Opciones de envío"
            >
              <ChevronDown className="size-3" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConversationThread({
  conversationId,
  onOpenCommand,
}: {
  conversationId: string | null;
  onOpenCommand: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const conversation = useConversation(conversationId ?? "");
  const messages = useMessages(conversationId ?? "");
  const messageItems = messages.data?.pages.flatMap((page) => page.items) ?? [];
  const grouped = useMemo(() => groupMessages(messageItems), [messageItems]);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (!containerRef.current) return;
      containerRef.current.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" });
    });
  }, []);

  useConversationStream(conversationId ?? "", scrollToBottom);

  useEffect(() => {
    if (!conversationId) return;
    if (messageItems.length === 0) return;
    requestAnimationFrame(() => {
      if (!containerRef.current) return;
      containerRef.current.scrollTo({ top: containerRef.current.scrollHeight });
    });
  }, [conversationId, messageItems.length]);

  if (!conversationId) {
    return (
      <section
        className="flex min-w-0 flex-1 flex-col bg-background"
        aria-label="Conversacion activa"
      >
        <EmptyState
          icon={MessageCircle}
          title="Selecciona una conversación"
          hint="La vista de mensajes se mantiene aquí para evitar saltos entre pantallas."
          action={{ label: "Buscar conversación", onClick: onOpenCommand }}
        />
      </section>
    );
  }

  if (conversation.isLoading) {
    return (
      <section
        className="flex min-w-0 flex-1 flex-col bg-background"
        aria-label="Conversacion activa"
      >
        <div className="flex h-14 items-center gap-3 border-b px-4">
          <Skeleton className="size-8 rounded-full" />
          <div className="space-y-1">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="h-3 w-28" />
          </div>
        </div>
        <div className="flex-1 space-y-3 p-4">
          <Skeleton className="h-10 w-1/2 rounded-lg" />
          <Skeleton className="ml-auto h-12 w-2/3 rounded-lg" />
          <Skeleton className="h-16 w-3/5 rounded-lg" />
        </div>
      </section>
    );
  }

  if (conversation.isError || !conversation.data) {
    return (
      <section
        className="flex min-w-0 flex-1 flex-col bg-background"
        aria-label="Conversacion activa"
      >
        <EmptyState
          icon={ShieldAlert}
          title="No se pudo abrir"
          hint="Actualiza la lista o elige otra conversación."
          action={{ label: "Reintentar", onClick: () => void conversation.refetch() }}
        />
      </section>
    );
  }

  const conv = conversation.data;

  return (
    <section
      className="flex min-w-0 flex-1 flex-col bg-background"
      aria-label="Conversacion activa"
    >
      <ConversationHeader conversation={conv} />
      <div ref={containerRef} className="min-h-0 flex-1 overflow-y-auto bg-muted/20 px-4 py-3">
        {messages.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-9 w-1/2 rounded-lg" />
            <Skeleton className="ml-auto h-12 w-2/3 rounded-lg" />
            <Skeleton className="h-16 w-3/5 rounded-lg" />
            <Skeleton className="ml-auto h-10 w-1/3 rounded-lg" />
          </div>
        ) : messageItems.length === 0 ? (
          <EmptyState
            icon={MessageCircle}
            title="Sin mensajes todavía"
            hint="Cuando entre el primer WhatsApp, aparecerá en este hilo."
            action={{ label: "Actualizar hilo", onClick: () => void messages.refetch() }}
          />
        ) : (
          <div className="space-y-3">
            {messages.hasNextPage && (
              <div className="flex justify-center">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => messages.fetchNextPage()}
                  disabled={messages.isFetchingNextPage}
                >
                  Cargar anteriores
                </Button>
              </div>
            )}
            {grouped.map((group) => (
              <div key={group.key} className="space-y-2">
                <div className="sticky top-0 z-10 flex justify-center py-1">
                  <span className="rounded-full border bg-background px-2 py-0.5 text-[10px] font-medium text-muted-foreground shadow-xs">
                    {group.label}
                  </span>
                </div>
                {group.items.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
      <Composer
        conversationId={conv.id}
        botPaused={conv.bot_paused}
        lastIntent={conv.last_intent}
      />
    </section>
  );
}

function CommandSearch({
  open,
  onOpenChange,
  query,
  onQueryChange,
  items,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: string;
  onQueryChange: (query: string) => void;
  items: ConversationListItem[];
  onSelect: (item: ConversationListItem) => void;
}) {
  const results = useMemo(() => {
    const trimmed = query.trim();
    if (!trimmed) return items.slice(0, 8);
    return items.filter((item) => matchesSearch(item, trimmed)).slice(0, 12);
  }, [items, query]);

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Buscar conversaciones"
      description="Busca por nombre, teléfono o último mensaje."
      className="max-w-2xl"
    >
      <Label htmlFor="conversation-command-search" className="sr-only">
        Buscar conversaciones
      </Label>
      <CommandInput
        id="conversation-command-search"
        value={query}
        onValueChange={onQueryChange}
        placeholder="Buscar por nombre, teléfono o mensaje"
      />
      <CommandList className="max-h-[420px]">
        <CommandEmpty>Sin resultados.</CommandEmpty>
        <CommandGroup heading="Conversaciones">
          {results.map((item) => {
            const visual = stageVisual(item.current_stage, item);
            return (
              <CommandItem
                key={item.id}
                value={`${item.customer_name ?? ""} ${item.customer_phone} ${item.last_message_text ?? ""}`}
                onSelect={() => {
                  onSelect(item);
                  onOpenChange(false);
                }}
              >
                <Avatar
                  className={cn("size-7 ring-2 ring-offset-1 ring-offset-background", visual.ring)}
                >
                  <AvatarFallback className="text-[10px]">{initialsFrom(item)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {item.customer_name ?? item.customer_phone}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {item.customer_phone} · {item.last_message_text ?? "Sin mensajes"}
                  </div>
                </div>
                <CommandShortcut>{formatRelative(item.last_activity_at)}</CommandShortcut>
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

export function ConversationsPage() {
  useTenantStream();

  const user = useAuthStore((state: { user: AuthUser | null }) => state.user);
  const queryClient = useQueryClient();
  const [railExpanded, setRailExpanded] = useState(
    () => localStorage.getItem("conv_rail") !== "collapsed",
  );
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [quickFilters, setQuickFilters] = useState<Set<QuickFilterId>>(() => new Set());
  const [search, setSearch] = useState(() => localStorage.getItem("conv_search") ?? "");
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  const conversations = useConversations({ limit: LIST_LIMIT });
  const allItems = conversations.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedConversation = useConversation(selectedConversationId ?? "");
  const selectedListItem = useMemo(
    () => allItems.find((item) => item.id === selectedConversationId),
    [allItems, selectedConversationId],
  );
  const selectedCustomerId =
    selectedConversation.data?.customer_id ?? selectedListItem?.customer_id;

  const inboxConfigQuery = useQuery({
    queryKey: ["tenants", "inbox-config"],
    queryFn: inboxConfigApi.get,
    staleTime: 60_000,
  });
  const inboxConfig = inboxConfigQuery.data ?? DEFAULT_INBOX_CONFIG;
  const filterChips = inboxConfig.filter_chips;
  const stageRings = inboxConfig.stage_rings;

  const markRead = useMutation({
    mutationFn: (id: string) => conversationsApi.markRead(id),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["conversation", id] });
    },
  });

  useEffect(() => {
    localStorage.setItem("conv_rail", railExpanded ? "expanded" : "collapsed");
  }, [railExpanded]);

  useEffect(() => {
    localStorage.setItem("conv_search", search);
  }, [search]);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
        return;
      }
      if (mod && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setRailExpanded((current) => !current);
        return;
      }
      if (event.key === "Escape") {
        setContextMenu(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const counts = useMemo<Record<QuickFilterId, number>>(
    () => ({
      unread: allItems.filter((item) => item.unread_count > 0).length,
      mine: allItems.filter((item) => item.assigned_user_id === user?.id).length,
      unassigned: allItems.filter((item) => item.assigned_user_id === null).length,
      awaiting_customer: allItems.filter(isAwaitingCustomer).length,
      stale: allItems.filter(isStaleConversation).length,
    }),
    [allItems, user?.id],
  );

  const visibleItems = useMemo(() => {
    let items = allItems;
    if (search.trim()) items = items.filter((item) => matchesSearch(item, search.trim()));
    if (activeStage) items = items.filter((item) => item.current_stage === activeStage);
    if (activeAgent)
      items = items.filter((item) => (item.assigned_user_email ?? "Sin asignar") === activeAgent);
    if (quickFilters.has("unread")) items = items.filter((item) => item.unread_count > 0);
    if (quickFilters.has("mine"))
      items = items.filter((item) => item.assigned_user_id === user?.id);
    if (quickFilters.has("unassigned"))
      items = items.filter((item) => item.assigned_user_id === null);
    if (quickFilters.has("awaiting_customer")) items = items.filter(isAwaitingCustomer);
    if (quickFilters.has("stale")) items = items.filter(isStaleConversation);
    return items;
  }, [activeAgent, activeStage, allItems, quickFilters, search, user?.id]);

  const hasActiveFilters =
    search.trim().length > 0 ||
    activeStage !== null ||
    activeAgent !== null ||
    quickFilters.size > 0;

  useEffect(() => {
    if (
      selectedConversationId &&
      (visibleItems.some((item) => item.id === selectedConversationId) ||
        (!hasActiveFilters && allItems.some((item) => item.id === selectedConversationId)))
    ) {
      return;
    }
    setSelectedConversationId(
      visibleItems[0]?.id ?? (hasActiveFilters ? null : allItems[0]?.id) ?? null,
    );
  }, [allItems, hasActiveFilters, selectedConversationId, visibleItems]);

  const allStages = useMemo(() => {
    const set = new Set(allItems.map((item) => item.current_stage));
    return Array.from(set).sort();
  }, [allItems]);

  const toggleFilter = useCallback((filter: QuickFilterId) => {
    setQuickFilters((current) => {
      const next = new Set(current);
      if (next.has(filter)) {
        next.delete(filter);
      } else {
        next.add(filter);
      }
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    setQuickFilters(new Set());
    setSearch("");
    setActiveAgent(null);
    setActiveStage(null);
  }, []);

  const selectConversation = useCallback(
    (row: ConversationListItem) => {
      setSelectedConversationId(row.id);
      if (row.unread_count > 0 && !markRead.isPending) {
        markRead.mutate(row.id);
      }
    },
    [markRead],
  );

  const handleContextMenu = useCallback((e: MouseEvent, conv: ConversationListItem) => {
    setContextMenu({ x: e.clientX, y: e.clientY, conv });
  }, []);

  if (conversations.isLoading) {
    return <InboxSkeleton />;
  }

  if (conversations.isError) {
    return (
      <div className="-m-6 flex h-[calc(100vh-3.5rem)] items-center justify-center bg-card">
        <EmptyState
          icon={ShieldAlert}
          title="No se pudo cargar el inbox"
          hint={conversations.error.message}
          action={{ label: "Reintentar", onClick: () => void conversations.refetch() }}
        />
      </div>
    );
  }

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col overflow-hidden bg-card text-foreground">
      {/* Three-panel area */}
      <div className="flex min-h-0 flex-1 overflow-hidden border-b">
        <FilterRail
          expanded={railExpanded}
          onExpandedChange={setRailExpanded}
          items={allItems}
          activeStage={activeStage}
          activeAgent={activeAgent}
          onStageChange={setActiveStage}
          onAgentChange={setActiveAgent}
          stageRings={stageRings}
        />
        <ConversationListPane
          items={visibleItems}
          selectedId={selectedConversationId}
          quickFilters={quickFilters}
          counts={counts}
          commandShortcut={commandHint()}
          search={search}
          hasActiveFilters={hasActiveFilters}
          onSearchChange={setSearch}
          onOpenCommand={() => setCommandOpen(true)}
          onToggleFilter={toggleFilter}
          onClearFilters={clearFilters}
          onSelect={selectConversation}
          onContextMenu={handleContextMenu}
          hasNextPage={!!conversations.hasNextPage}
          isFetchingNextPage={conversations.isFetchingNextPage}
          onFetchNextPage={() => void conversations.fetchNextPage()}
          filterChips={filterChips}
          stageRings={stageRings}
        />
        <ConversationThread
          conversationId={selectedConversationId}
          onOpenCommand={() => setCommandOpen(true)}
        />
        <div className="hidden min-h-0 shrink-0 p-2 xl:flex">
          <ContactPanel
            customerId={selectedCustomerId}
            conversation={selectedConversation.data}
          />
        </div>
      </div>

      {/* Keyboard shortcuts bar */}
      <div className="flex h-7 shrink-0 items-center justify-between bg-muted/40 px-4 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-4">
          {[
            ["⌘K", "Buscar"],
            ["⌘B", "Filtros"],
            ["⌘/", "Atajos"],
            ["↑↓", "Navegar"],
            ["Enter", "Enviar"],
            ["Esc", "Cerrar"],
          ].map(([key, label]) => (
            <span key={key} className="flex items-center gap-1">
              <kbd className="rounded border bg-background px-1 py-0.5 font-mono text-[9px] shadow-sm">
                {key}
              </kbd>
              {label}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-emerald-500" />
            Conectado
          </span>
          <button
            type="button"
            className="flex items-center gap-1 hover:text-foreground"
            onClick={() => void conversations.refetch()}
            title="Actualizar"
          >
            <RefreshCw className="size-2.5" />
            Actualizar
          </button>
        </div>
      </div>

      <CommandSearch
        open={commandOpen}
        onOpenChange={setCommandOpen}
        query={commandQuery}
        onQueryChange={setCommandQuery}
        items={allItems}
        onSelect={selectConversation}
      />
      {contextMenu && (
        <ConversationContextMenu
          menu={contextMenu}
          onClose={() => setContextMenu(null)}
          allStages={allStages}
          currentUserId={user?.id}
        />
      )}
    </div>
  );
}

export { ConversationsPage as ConversationList };

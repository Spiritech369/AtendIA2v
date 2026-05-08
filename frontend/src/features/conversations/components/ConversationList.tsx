import { Link } from "@tanstack/react-router";
import {
  Bot,
  Circle,
  Copy,
  Hand,
  Inbox,
  Search,
  ShieldAlert,
  Trash2,
  User,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ConversationListItem } from "@/features/conversations/api";
import { useConversations } from "@/features/conversations/hooks/useConversations";
import { useTenantStream } from "@/features/conversations/hooks/useTenantStream";
import { cn } from "@/lib/utils";

// ── Constants ────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  active: "bg-emerald-500",
  waiting_human: "bg-amber-500",
  with_human: "bg-sky-500",
  closed: "bg-slate-400",
};

const STATUS_LABELS: Record<string, string> = {
  active: "Bot activo",
  waiting_human: "Espera agente",
  with_human: "Con agente",
  closed: "Cerrada",
};

type InboxTab = "all" | "handoffs" | "paused";

function getStoredTab(): InboxTab {
  const stored = localStorage.getItem("conv_tab");
  if (stored === "handoffs" || stored === "paused") return stored;
  return "all";
}

function getStoredSearch(): string {
  return localStorage.getItem("conv_search") ?? "";
}

// ── Helpers ──────────────────────────────────────────────────────────

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

function matchesSearch(conv: ConversationListItem, query: string): boolean {
  const q = query.toLowerCase();
  return (
    (conv.customer_name?.toLowerCase().includes(q) ?? false) ||
    conv.customer_phone.toLowerCase().includes(q) ||
    (conv.last_message_text?.toLowerCase().includes(q) ?? false) ||
    conv.current_stage.toLowerCase().includes(q)
  );
}

// ── Context menu ─────────────────────────────────────────────────────

interface ContextMenuState {
  x: number;
  y: number;
  conv: ConversationListItem;
}

function ConversationContextMenu({
  menu,
  onClose,
}: {
  menu: ContextMenuState;
  onClose: () => void;
}) {
  const handleCopyPhone = useCallback(() => {
    void navigator.clipboard.writeText(menu.conv.customer_phone).then(() => {
      toast.success("Teléfono copiado");
    });
    onClose();
  }, [menu.conv.customer_phone, onClose]);

  // Clamp position so menu doesn't overflow viewport
  const MENU_W = 220;
  const MENU_H = 160;
  const x = Math.min(menu.x, window.innerWidth - MENU_W - 8);
  const y = Math.min(menu.y, window.innerHeight - MENU_H - 8);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-50" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        className="fixed z-50 rounded-md border bg-popover p-1 shadow-md"
        style={{ left: x, top: y, width: MENU_W }}
      >
        <Link
          to="/conversations/$conversationId"
          params={{ conversationId: menu.conv.id }}
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
          onClick={onClose}
        >
          <Inbox className="h-4 w-4" /> Abrir conversación
        </Link>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
          onClick={handleCopyPhone}
        >
          <Copy className="h-4 w-4" /> Copiar teléfono
        </button>
        <Separator className="my-1" />
        <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Etapa: {menu.conv.current_stage}
        </div>
        <div className="px-2 py-1 text-[10px] text-muted-foreground">
          {menu.conv.bot_paused ? "Bot pausado" : STATUS_LABELS[menu.conv.status] ?? menu.conv.status}
        </div>
      </div>
    </>
  );
}

// ── Sidebar: stage counts ────────────────────────────────────────────

function StageSidebar({
  items,
  activeStage,
  onSelect,
}: {
  items: ConversationListItem[];
  activeStage: string | null;
  onSelect: (stage: string | null) => void;
}) {
  const stageCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const c of items) {
      map.set(c.current_stage, (map.get(c.current_stage) ?? 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [items]);

  if (stageCounts.length === 0) return null;

  return (
    <div className="space-y-0.5">
      <div className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        Etapas
      </div>
      <button
        type="button"
        className={cn(
          "flex w-full items-center justify-between rounded-sm px-2 py-1 text-xs hover:bg-accent",
          activeStage === null && "bg-accent font-medium",
        )}
        onClick={() => onSelect(null)}
      >
        <span>Todas</span>
        <span className="text-muted-foreground">{items.length}</span>
      </button>
      {stageCounts.map(([stage, count]) => (
        <button
          key={stage}
          type="button"
          className={cn(
            "flex w-full items-center justify-between rounded-sm px-2 py-1 text-xs hover:bg-accent",
            activeStage === stage && "bg-accent font-medium",
          )}
          onClick={() => onSelect(activeStage === stage ? null : stage)}
        >
          <span className="truncate">{stage}</span>
          <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
            {count}
          </Badge>
        </button>
      ))}
    </div>
  );
}

// ── Conversation row ─────────────────────────────────────────────────

function ConversationRow({
  row,
  onContextMenu,
}: {
  row: ConversationListItem;
  onContextMenu: (e: React.MouseEvent, conv: ConversationListItem) => void;
}) {
  const statusColor = STATUS_COLORS[row.status] ?? "bg-slate-400";

  return (
    <Link
      to="/conversations/$conversationId"
      params={{ conversationId: row.id }}
      className="group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-accent"
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(e, row);
      }}
    >
      {/* Status dot */}
      <div className="mt-1.5 shrink-0">
        <Circle className={cn("h-2.5 w-2.5 fill-current", statusColor, "text-transparent")} />
      </div>

      {/* Main content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm font-medium">
            {row.customer_name ?? row.customer_phone}
          </span>
          <span className="shrink-0 text-[10px] text-muted-foreground">
            {formatRelative(row.last_activity_at)}
          </span>
        </div>

        {row.customer_name && (
          <div className="text-xs text-muted-foreground">{row.customer_phone}</div>
        )}

        {/* Last message preview */}
        <div className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
          {row.last_message_direction === "inbound" ? (
            <User className="h-3 w-3 shrink-0" />
          ) : (
            <Bot className="h-3 w-3 shrink-0" />
          )}
          <span className="truncate">{row.last_message_text ?? "(sin mensajes)"}</span>
        </div>

        {/* Badges row */}
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge variant="outline" className="h-4 px-1 text-[10px]">
            {row.current_stage}
          </Badge>
          {row.has_pending_handoff && (
            <Badge variant="destructive" className="h-4 gap-0.5 px-1 text-[10px]">
              <ShieldAlert className="h-2.5 w-2.5" /> Handoff
            </Badge>
          )}
          {row.bot_paused && (
            <Badge variant="secondary" className="h-4 gap-0.5 px-1 text-[10px]">
              <Hand className="h-2.5 w-2.5" /> Pausado
            </Badge>
          )}
        </div>
      </div>
    </Link>
  );
}

// ── Main component ───────────────────────────────────────────────────

export function ConversationList() {
  useTenantStream();

  const [tab, setTab] = useState<InboxTab>(getStoredTab);
  const [search, setSearch] = useState(getStoredSearch);
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  // Map tab → API filter params
  const filters = useMemo(() => {
    const base = { limit: 100 };
    if (tab === "handoffs") return { ...base, has_pending_handoff: true as const };
    if (tab === "paused") return { ...base, bot_paused: true as const };
    return base;
  }, [tab]);

  const query = useConversations(filters);

  const handleTabChange = useCallback((value: string) => {
    const t = value as InboxTab;
    setTab(t);
    setActiveStage(null);
    localStorage.setItem("conv_tab", t);
  }, []);

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    localStorage.setItem("conv_search", value);
  }, []);

  const handleContextMenu = useCallback((e: React.MouseEvent, conv: ConversationListItem) => {
    setContextMenu({ x: e.clientX, y: e.clientY, conv });
  }, []);

  const allItems = query.data?.pages.flatMap((p) => p.items) ?? [];

  // Client-side filtering: search + stage
  const visibleItems = useMemo(() => {
    let items = allItems;
    if (search.trim()) {
      items = items.filter((c) => matchesSearch(c, search.trim()));
    }
    if (activeStage) {
      items = items.filter((c) => c.current_stage === activeStage);
    }
    return items;
  }, [allItems, search, activeStage]);

  // Counts for tab badges
  const counts = useMemo(() => {
    const all = allItems;
    return {
      all: all.length,
      handoffs: tab === "handoffs" ? all.length : all.filter((c) => c.has_pending_handoff).length,
      paused: tab === "paused" ? all.length : all.filter((c) => c.bot_paused).length,
    };
  }, [allItems, tab]);

  if (query.isLoading) {
    return (
      <Card className="flex h-full flex-col">
        <div className="space-y-2 p-4">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      </Card>
    );
  }

  if (query.isError) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-destructive">
          Error al cargar conversaciones: {query.error.message}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex h-full gap-4">
      {/* Stage sidebar */}
      <Card className="hidden w-48 shrink-0 lg:flex lg:flex-col">
        <div className="p-3">
          <div className="mb-2 text-sm font-semibold">Buzón</div>
          <StageSidebar items={allItems} activeStage={activeStage} onSelect={setActiveStage} />
        </div>
      </Card>

      {/* Main list */}
      <Card className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Search + Tabs header */}
        <div className="space-y-2 border-b p-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar por nombre, teléfono o mensaje…"
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="pl-9"
            />
          </div>
          <Tabs value={tab} onValueChange={handleTabChange}>
            <TabsList className="w-full">
              <TabsTrigger value="all" className="flex-1 gap-1">
                Todos
                <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                  {counts.all}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="handoffs" className="flex-1 gap-1">
                Handoffs
                {counts.handoffs > 0 && (
                  <Badge variant="destructive" className="ml-1 h-4 px-1 text-[10px]">
                    {counts.handoffs}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="paused" className="flex-1 gap-1">
                Pausados
                {counts.paused > 0 && (
                  <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                    {counts.paused}
                  </Badge>
                )}
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        {/* Conversation rows */}
        <ScrollArea className="flex-1">
          <div className="divide-y">
            {visibleItems.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                {search.trim()
                  ? "Sin resultados para esta búsqueda."
                  : "Sin conversaciones en esta vista."}
              </div>
            ) : (
              visibleItems.map((row) => (
                <ConversationRow
                  key={row.id}
                  row={row}
                  onContextMenu={handleContextMenu}
                />
              ))
            )}
          </div>
          {query.hasNextPage && (
            <div className="flex justify-center py-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => query.fetchNextPage()}
                disabled={query.isFetchingNextPage}
              >
                {query.isFetchingNextPage ? "Cargando…" : "Cargar más"}
              </Button>
            </div>
          )}
        </ScrollArea>
      </Card>

      {/* Context menu */}
      {contextMenu && (
        <ConversationContextMenu menu={contextMenu} onClose={() => setContextMenu(null)} />
      )}
    </div>
  );
}

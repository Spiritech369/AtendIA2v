import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  BarChart3,
  Bell,
  BookOpen,
  Bug,
  CalendarDays,
  Columns3,
  Database,
  FileText,
  LayoutDashboard,
  LogOut,
  MessageCircle,
  Network,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { notificationsApi } from "@/features/notifications/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { WhatsAppStatusBadge } from "./WhatsAppStatusBadge";

interface NavItem {
  to: string;
  label: string;
  icon: typeof MessageCircle;
  tenantAdminOnly?: boolean;
  superadminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/", label: "Conversaciones", icon: MessageCircle },
  { to: "/handoffs", label: "Handoffs", icon: ShieldCheck },
  { to: "/customers", label: "Clientes", icon: Users },
  { to: "/pipeline", label: "Pipeline", icon: Columns3 },
  { to: "/appointments", label: "Citas", icon: CalendarDays },
  { to: "/knowledge", label: "Conocimiento", icon: BookOpen },
  { to: "/analytics", label: "Analítica", icon: BarChart3 },
  { to: "/turn-traces", label: "Debug de turnos", icon: Bug },
  { to: "/config", label: "Configuración", icon: Settings },
  { to: "/inbox-settings", label: "Config. Bandeja", icon: SlidersHorizontal },
  { to: "/agents", label: "Agentes IA", icon: Sparkles, tenantAdminOnly: true },
  { to: "/workflows", label: "Workflows", icon: Network },
  { to: "/users", label: "Usuarios", icon: UserRound, tenantAdminOnly: true },
  { to: "/audit-log", label: "Auditoría", icon: FileText, superadminOnly: true },
  { to: "/exports", label: "Exportar", icon: Database },
];

export function AppShell({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const path = useRouterState({ select: (s) => s.location.pathname });
  const isHandoffCommandCenter = path === "/handoffs" || path.startsWith("/handoffs/");

  const visible = NAV_ITEMS.filter((item) => {
    if (item.superadminOnly) return user?.role === "superadmin";
    if (item.tenantAdminOnly) return user?.role === "tenant_admin" || user?.role === "superadmin";
    return true;
  });

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "??";

  return (
    <div
      className={cn(
        "flex h-screen overflow-hidden",
        isHandoffCommandCenter ? "bg-[#050b14]" : "bg-background",
      )}
    >
      <aside
        className={cn(
          "flex w-60 shrink-0 flex-col border-r",
          isHandoffCommandCenter
            ? "border-slate-800 bg-[#050b14] text-slate-300"
            : "bg-sidebar text-sidebar-foreground",
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center gap-2 px-4 font-semibold",
            isHandoffCommandCenter && "text-white",
          )}
        >
          <span
            className={cn(
              "grid h-7 w-7 place-items-center rounded-md text-xs",
              isHandoffCommandCenter
                ? "border border-blue-400/30 bg-blue-600 text-white shadow-lg shadow-blue-950/40"
                : "bg-primary text-primary-foreground",
            )}
          >
            AI
          </span>
          AtendIA
        </div>
        <Separator className={isHandoffCommandCenter ? "bg-slate-800" : undefined} />
        <ScrollArea className="flex-1 px-2 py-3">
          <nav className="flex flex-col gap-1">
            {visible.map((item) => {
              const Icon = item.icon;
              const active = path === item.to || path.startsWith(`${item.to}/`);
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                    isHandoffCommandCenter
                      ? active
                        ? "bg-blue-600/20 text-white ring-1 ring-blue-500/30"
                        : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
                      : active
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </ScrollArea>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header
          className={cn(
            "flex h-14 items-center justify-between border-b px-6",
            isHandoffCommandCenter
              ? "border-slate-800 bg-[#07101b] text-slate-200"
              : "bg-background",
          )}
        >
          <div className="flex items-center gap-4">
            <span
              className={cn(
                "text-sm",
                isHandoffCommandCenter ? "text-slate-400" : "text-muted-foreground",
              )}
            >
              {user?.role === "superadmin" ? "Superadmin" : `Tenant: ${user?.tenant_id ?? "—"}`}
            </span>
            <WhatsAppStatusBadge />
          </div>
          <div className="flex items-center gap-3">
            <NotificationsDropdown />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="gap-2 px-2">
                  <Avatar className="h-7 w-7">
                    <AvatarFallback className="text-xs">{initials}</AvatarFallback>
                  </Avatar>
                  <span className="text-sm">{user?.email}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel className="text-xs text-muted-foreground">
                  {user?.role}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={async () => {
                    await logout();
                    window.location.assign("/login");
                  }}
                >
                  <LogOut className="mr-2 h-4 w-4" /> Cerrar sesión
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}

function NotificationsDropdown() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: notificationsApi.list,
    refetchInterval: 30_000,
  });
  const markRead = useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const markAll = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = query.data?.unread_count ?? 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Notificaciones" className="relative">
          <Bell className="h-4 w-4" />
          {unread > 0 && (
            <Badge className="absolute -right-1 -top-1 h-5 min-w-5 px-1 text-[10px]">
              {unread}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          Notificaciones
          {unread > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => markAll.mutate()}
            >
              Leer todas
            </Button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <ScrollArea className="max-h-80">
          {(query.data?.items ?? []).length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              Sin notificaciones.
            </div>
          ) : (
            query.data?.items.map((item) => (
              <DropdownMenuItem
                key={item.id}
                className="flex cursor-pointer flex-col items-start gap-1 py-2"
                onClick={() => {
                  if (!item.read) markRead.mutate(item.id);
                }}
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <span className={cn("text-sm", !item.read && "font-semibold")}>{item.title}</span>
                  {!item.read && <span className="h-2 w-2 rounded-full bg-primary" />}
                </div>
                {item.body && (
                  <span className="line-clamp-2 text-xs text-muted-foreground">{item.body}</span>
                )}
              </DropdownMenuItem>
            ))
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

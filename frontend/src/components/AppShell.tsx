import { Link, useRouterState } from "@tanstack/react-router";
import {
  BarChart3,
  Bell,
  Bug,
  Database,
  FileText,
  LogOut,
  MessageCircle,
  Settings,
  ShieldCheck,
  UserRound,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { WhatsAppStatusBadge } from "./WhatsAppStatusBadge";

interface NavItem {
  to: string;
  label: string;
  icon: typeof MessageCircle;
  superadminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Conversaciones", icon: MessageCircle },
  { to: "/handoffs", label: "Handoffs", icon: ShieldCheck },
  { to: "/customers", label: "Clientes", icon: Users },
  { to: "/analytics", label: "Analítica", icon: BarChart3 },
  { to: "/turn-traces", label: "Debug de turnos", icon: Bug },
  { to: "/config", label: "Configuración", icon: Settings },
  { to: "/users", label: "Usuarios", icon: UserRound, superadminOnly: true },
  { to: "/audit-log", label: "Auditoría", icon: FileText, superadminOnly: true },
  { to: "/exports", label: "Exportar", icon: Database },
];

export function AppShell({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const path = useRouterState({ select: (s) => s.location.pathname });

  const visible = NAV_ITEMS.filter((item) => !item.superadminOnly || user?.role === "superadmin");

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "??";

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
        <div className="flex h-14 items-center gap-2 px-4 font-semibold tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-primary text-primary-foreground text-xs">
            AI
          </span>
          AtendIA
        </div>
        <Separator />
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
                    active
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
        <header className="flex h-14 items-center justify-between border-b px-6">
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              {user?.role === "superadmin" ? "Superadmin" : `Tenant: ${user?.tenant_id ?? "—"}`}
            </span>
            <WhatsAppStatusBadge />
          </div>
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" aria-label="Notificaciones">
              <Bell className="h-4 w-4" />
            </Button>
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

import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuthStore } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar-store";

const ROLE_LABELS: Record<string, string> = {
  operator: "Operador",
  tenant_admin: "Admin tenant",
  superadmin: "Superadmin",
  supervisor: "Supervisor",
  manager: "Manager",
  sales_agent: "Vendedor",
  ai_reviewer: "Revisor IA",
};

/**
 * Pinned to the bottom of the sidebar: avatar, email, role chip and the
 * compact toggle. Logout sits here too — moving it out of the global
 * header keeps the top-right reserved for notifications.
 */
export function SidebarFooter() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const compact = useSidebarStore((s) => s.compact);
  const toggleCompact = useSidebarStore((s) => s.toggleCompact);

  if (!user) return null;
  const initials = user.email.slice(0, 2).toUpperCase();
  const roleLabel = ROLE_LABELS[user.role] ?? user.role;

  return (
    <>
      <Separator />
      <div className="flex shrink-0 items-center gap-2 px-3 py-3">
        <Avatar className="h-7 w-7 shrink-0">
          <AvatarFallback className="text-[10px]">{initials}</AvatarFallback>
        </Avatar>
        {!compact && (
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium">{user.email}</div>
            <div className="text-[10px] text-muted-foreground">{roleLabel}</div>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          aria-label={compact ? "Expandir menú" : "Compactar menú"}
          onClick={toggleCompact}
        >
          {compact ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </Button>
        {!compact && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            aria-label="Cerrar sesión"
            onClick={async () => {
              await logout();
              window.location.assign("/login");
            }}
          >
            <LogOut className="h-4 w-4" />
          </Button>
        )}
      </div>
    </>
  );
}

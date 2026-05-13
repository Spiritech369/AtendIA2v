import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { filterMenuByRole, NAV_GROUPS } from "@/features/navigation/menu-config";
import { useNavBadges } from "@/features/navigation/hooks";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar-store";

import { SidebarFooter } from "./SidebarFooter";
import { SidebarGroup } from "./SidebarGroup";
import { SidebarHeader } from "./SidebarHeader";

/**
 * Main sidebar shell. Renders header + scrollable groups + footer.
 * - Filters menu by current user role.
 * - Polls navigation badges every 30s via useNavBadges.
 * - Width animates between w-60 and w-14 in compact mode.
 */
export function AppSidebar() {
  const user = useAuthStore((s) => s.user);
  const compact = useSidebarStore((s) => s.compact);
  const path = useRouterState({ select: (s) => s.location.pathname });
  const badges = useNavBadges();

  const groups = useMemo(
    () => filterMenuByRole(NAV_GROUPS, user?.role),
    [user?.role],
  );

  return (
    <aside
      aria-label="Navegación principal"
      className={cn(
        "flex h-full shrink-0 flex-col overflow-hidden border-r bg-sidebar text-sidebar-foreground transition-[width] duration-150",
        compact ? "w-14" : "w-60",
      )}
    >
      <SidebarHeader tenantId={user?.tenant_id ?? null} compact={compact} />
      <div className="flex-1 overflow-y-auto py-2">
        {!user ? (
          <div className="space-y-3 px-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-full" />
          </div>
        ) : (
          <nav className="flex flex-col gap-3">
            {groups.map((group) => (
              <SidebarGroup
                key={group.id}
                group={group}
                compact={compact}
                activePath={path}
                badges={badges.data}
              />
            ))}
          </nav>
        )}
      </div>
      <SidebarFooter />
    </aside>
  );
}

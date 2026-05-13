import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import type { ReactNode } from "react";

import { AppSidebar } from "@/components/sidebar/AppSidebar";
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
import { notificationsApi } from "@/features/notifications/api";
import { cn } from "@/lib/utils";

/**
 * AppShell now delegates the entire left rail to <AppSidebar />.
 * The top bar only keeps the global notifications dropdown — user
 * info and logout moved into the sidebar footer where there's room
 * for the role chip and the compact toggle.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const isHandoffCommandCenter = path === "/handoffs" || path.startsWith("/handoffs/");

  return (
    <div
      className={cn(
        "flex h-screen overflow-hidden",
        isHandoffCommandCenter ? "bg-[#050b14]" : "bg-background",
      )}
    >
      <AppSidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header
          className={cn(
            "flex h-12 items-center justify-end gap-3 border-b px-6",
            isHandoffCommandCenter
              ? "border-slate-800 bg-[#07101b] text-slate-200"
              : "bg-background",
          )}
        >
          <NotificationsDropdown />
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

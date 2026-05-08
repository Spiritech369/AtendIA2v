import { createFileRoute } from "@tanstack/react-router";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/stores/auth";

/**
 * Authed dashboard root — placeholder until T12 lands the real AppShell
 * (sidebar + 9 pillars). For now, just confirms login worked.
 */
export const Route = createFileRoute("/(auth)/")({
  component: DashboardHome,
});

function DashboardHome() {
  const user = useAuthStore((s) => s.user);
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-8">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Hola, {user?.email}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>Rol: {user?.role}</p>
          <p>Tenant: {user?.tenant_id ?? "(superadmin — sin tenant)"}</p>
          <p className="pt-4 text-xs">Dashboard real arriba en T12 — Block B.</p>
        </CardContent>
      </Card>
    </div>
  );
}

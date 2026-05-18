import { createFileRoute } from "@tanstack/react-router";

import { ExpedientePage } from "@/features/expediente/components/ExpedientePage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/expediente")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: ExpedientePage,
});

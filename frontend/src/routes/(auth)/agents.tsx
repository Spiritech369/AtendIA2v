import { createFileRoute } from "@tanstack/react-router";

import { AgentsPage } from "@/features/agents/components/AgentsPage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/agents")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: AgentsPage,
});

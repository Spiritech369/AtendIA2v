import { createFileRoute } from "@tanstack/react-router";

import { AgentsPage } from "@/features/agents/components/AgentsPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/agents")({
  beforeLoad: requireCapability("route.agents", ["tenant_admin", "superadmin"]),
  component: AgentsPage,
});

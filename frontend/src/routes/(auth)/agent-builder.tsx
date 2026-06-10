import { createFileRoute } from "@tanstack/react-router";

import { AgentBuilderPage } from "@/features/product-agent-builder/components/AgentBuilderPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/agent-builder")({
  beforeLoad: requireCapability("route.agents", ["tenant_admin", "superadmin"]),
  component: AgentBuilderPage,
});

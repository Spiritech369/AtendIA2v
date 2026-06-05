import { createFileRoute } from "@tanstack/react-router";

import { AgentsPage } from "@/features/agents/components/AgentsPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/agents/$agentId")({
  beforeLoad: requireCapability("route.agents", ["tenant_admin", "superadmin"]),
  component: AgentRoute,
});

function AgentRoute() {
  const { agentId } = Route.useParams();
  // Same AgentsPage component as /agents — the param just preselects
  // which agent is active in the sidebar so deep-links from the
  // DebugPanel (A15) land directly on the right editor.
  return <AgentsPage initialAgentId={agentId} />;
}

import { createFileRoute } from "@tanstack/react-router";

import { AgentsPage } from "@/features/agents/components/AgentsPage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/agents/$agentId")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: AgentRoute,
});

function AgentRoute() {
  const { agentId } = Route.useParams();
  // Same AgentsPage component as /agents — the param just preselects
  // which agent is active in the sidebar so deep-links from the
  // DebugPanel (A15) land directly on the right editor.
  return <AgentsPage initialAgentId={agentId} />;
}

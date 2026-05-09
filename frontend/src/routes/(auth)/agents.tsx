import { createFileRoute } from "@tanstack/react-router";

import { AgentsPage } from "@/features/agents/components/AgentsPage";

export const Route = createFileRoute("/(auth)/agents")({
  component: AgentsPage,
});

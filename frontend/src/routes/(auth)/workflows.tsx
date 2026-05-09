import { createFileRoute } from "@tanstack/react-router";

import { WorkflowsPage } from "@/features/workflows/components/WorkflowsPage";

export const Route = createFileRoute("/(auth)/workflows")({
  component: WorkflowsPage,
});

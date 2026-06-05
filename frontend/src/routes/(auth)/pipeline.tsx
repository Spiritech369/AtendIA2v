import { createFileRoute } from "@tanstack/react-router";

import { PipelineKanbanPage } from "@/features/pipeline/components/PipelineKanbanPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/pipeline")({
  beforeLoad: requireCapability("route.pipeline", ["tenant_admin", "superadmin"]),
  component: PipelineKanbanPage,
});

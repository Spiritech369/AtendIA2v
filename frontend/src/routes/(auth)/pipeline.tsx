import { createFileRoute } from "@tanstack/react-router";

import { PipelineKanbanPage } from "@/features/pipeline/components/PipelineKanbanPage";

export const Route = createFileRoute("/(auth)/pipeline")({
  component: PipelineKanbanPage,
});

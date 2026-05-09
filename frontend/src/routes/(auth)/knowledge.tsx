import { createFileRoute } from "@tanstack/react-router";

import { KnowledgeBasePage } from "@/features/knowledge/components/KnowledgeBasePage";

export const Route = createFileRoute("/(auth)/knowledge")({
  component: KnowledgeBasePage,
});

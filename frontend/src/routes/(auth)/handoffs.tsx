import { createFileRoute } from "@tanstack/react-router";

import { HandoffQueue } from "@/features/handoffs/components/HandoffQueue";

export const Route = createFileRoute("/(auth)/handoffs")({
  component: HandoffQueue,
});

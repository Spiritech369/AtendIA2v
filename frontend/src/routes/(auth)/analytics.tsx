import { createFileRoute } from "@tanstack/react-router";

import { AnalyticsDashboard } from "@/features/analytics/components/AnalyticsDashboard";

export const Route = createFileRoute("/(auth)/analytics")({
  component: AnalyticsDashboard,
});

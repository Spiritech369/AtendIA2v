import { createFileRoute } from "@tanstack/react-router";

import { ConfigLinterPage } from "@/features/config-linter/components/ConfigLinterPage";

export const Route = createFileRoute("/(auth)/config-linter")({
  component: ConfigLinterPage,
});

import { createFileRoute } from "@tanstack/react-router";

import { ComposerModesEditor } from "@/features/agents/components/ComposerModesEditor";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/composer")({
  beforeLoad: requireCapability("route.composer", ["tenant_admin", "superadmin"]),
  component: ComposerPage,
});

function ComposerPage() {
  return <ComposerModesEditor />;
}

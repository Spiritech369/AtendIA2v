import { createFileRoute } from "@tanstack/react-router";

import { ComposerModesEditor } from "@/features/agents/components/ComposerModesEditor";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/composer")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: ComposerPage,
});

function ComposerPage() {
  return <ComposerModesEditor />;
}

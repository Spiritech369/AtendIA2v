import { createFileRoute } from "@tanstack/react-router";

import { InboxSettingsPage } from "@/features/inbox-settings/components/InboxSettingsPage";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/inbox-settings")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: InboxSettingsPage,
});

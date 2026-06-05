import { createFileRoute } from "@tanstack/react-router";

import { InboxSettingsPage } from "@/features/inbox-settings/components/InboxSettingsPage";
import { requireCapability } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/inbox-settings")({
  beforeLoad: requireCapability("route.inbox_settings", ["tenant_admin", "superadmin"]),
  component: InboxSettingsPage,
});

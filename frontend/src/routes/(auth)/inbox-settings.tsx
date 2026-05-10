import { createFileRoute } from "@tanstack/react-router";

import { InboxSettingsPage } from "@/features/inbox-settings/components/InboxSettingsPage";

export const Route = createFileRoute("/(auth)/inbox-settings")({
  component: InboxSettingsPage,
});

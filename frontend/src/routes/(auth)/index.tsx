import { createFileRoute } from "@tanstack/react-router";

import { ConversationList } from "@/features/conversations/components/ConversationList";

export const Route = createFileRoute("/(auth)/")({
  component: () => <ConversationList />,
});

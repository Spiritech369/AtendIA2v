import { createFileRoute } from "@tanstack/react-router";

import { ConversationDetail } from "@/features/conversations/components/ConversationDetail";

export const Route = createFileRoute("/(auth)/conversations/$conversationId")({
  component: ConversationDetailPage,
});

function ConversationDetailPage() {
  const { conversationId } = Route.useParams();
  return <ConversationDetail conversationId={conversationId} />;
}

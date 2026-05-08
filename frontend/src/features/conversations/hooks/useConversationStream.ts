import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useWebSocket, type WSEvent } from "@/api/ws-client";
import { useAuthStore } from "@/stores/auth";

interface ConversationEvent extends WSEvent {
  conversation_id?: string;
}

/**
 * Per-conversation live stream. Sits on top of the tenant-wide WebSocket
 * (we don't open a second socket — `useTenantStream` mounted higher up
 * already pumps events into the query cache). This hook just adds a
 * focused listener for the detail page so it can scroll to bottom on
 * new messages.
 *
 * The plan T19 originally said "wraps /ws/conversations/:cid". For Phase 4
 * we converged on a single tenant socket because (a) the operator session
 * cookie is the only auth they have, and (b) keeping one socket per
 * dashboard is cheaper than re-opening per route. /ws/conversations/:cid
 * remains for non-dashboard clients (Phase 2 tooling) but the dashboard
 * does NOT use it.
 */
export function useConversationStream(
  conversationId: string,
  onMatch?: (e: ConversationEvent) => void,
): void {
  const queryClient = useQueryClient();
  const tenantId = useAuthStore((s) => s.user?.tenant_id);

  const onEvent = useCallback(
    (e: ConversationEvent) => {
      if (e.conversation_id !== conversationId) return;
      void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      void queryClient.invalidateQueries({ queryKey: ["messages", conversationId] });
      onMatch?.(e);
    },
    [conversationId, onMatch, queryClient],
  );

  useWebSocket<ConversationEvent>({
    path: tenantId ? `/ws/tenants/${tenantId}` : "",
    onEvent,
    enabled: !!tenantId && !!conversationId,
  });
}

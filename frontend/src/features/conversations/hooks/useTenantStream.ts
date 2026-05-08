import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useWebSocket, type WSEvent } from "@/api/ws-client";
import { useAuthStore } from "@/stores/auth";

interface ConversationEvent extends WSEvent {
  conversation_id?: string;
}

/**
 * Subscribes to /ws/tenants/<your-tenant>, invalidates the relevant
 * react-query caches whenever the backend emits an event.
 *
 * Operators get their tenant_id from the auth store. Superadmins are NOT
 * auto-subscribed here — they must explicitly pick a tenant first
 * (T28+ tenant switcher).
 *
 * Returns nothing; mount it once near the AppShell so every screen
 * reflects live data.
 */
export function useTenantStream(): void {
  const queryClient = useQueryClient();
  const tenantId = useAuthStore((s) => s.user?.tenant_id);

  const onEvent = useCallback(
    (e: ConversationEvent) => {
      // List queries always re-fetch.
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["handoffs"] });

      if (e.conversation_id) {
        void queryClient.invalidateQueries({ queryKey: ["conversation", e.conversation_id] });
        void queryClient.invalidateQueries({ queryKey: ["messages", e.conversation_id] });
      }
    },
    [queryClient],
  );

  useWebSocket<ConversationEvent>({
    path: tenantId ? `/ws/tenants/${tenantId}` : "",
    onEvent,
    enabled: !!tenantId,
  });
}

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useWebSocket, type WSEvent } from "@/api/ws-client";
import { useAuthStore } from "@/stores/auth";

interface ConversationEvent extends WSEvent {
  // Runner / queue worker emit a discriminator string; the WSEvent
  // contract already requires `type: string`, so we narrow to the
  // event names this hook handles. Anything else flows through as a
  // plain string and the switch below defaults to a no-op.
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
      // Config-shaped events carry no conversation_id; bail out of the
      // per-conversation invalidations and only refresh the caches that
      // depend on the config that changed.
      if (e.type === "pipeline_updated") {
        void queryClient.invalidateQueries({ queryKey: ["tenants", "pipeline"] });
        void queryClient.invalidateQueries({ queryKey: ["pipeline"] });
        return;
      }

      // List queries always re-fetch.
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["handoffs"] });

      if (e.conversation_id) {
        void queryClient.invalidateQueries({ queryKey: ["conversation", e.conversation_id] });
        void queryClient.invalidateQueries({ queryKey: ["messages", e.conversation_id] });

        // Fase 1 — runner-emitted system events that mutate customer or
        // conversation state. The messages query already picks up the
        // new system-row bubble; these extra invalidations refresh the
        // sidebar panels (ContactPanel attrs, required_docs, suggestions)
        // so the operator sees the new field/stage/doc state without a
        // manual reload.
        switch (e.type) {
          case "field_updated":
          case "field_extracted":
            void queryClient.invalidateQueries({ queryKey: ["customers"] });
            void queryClient.invalidateQueries({ queryKey: ["field-suggestions"] });
            break;
          case "stage_changed":
          case "stage_entered":
          case "stage_exited":
            void queryClient.invalidateQueries({ queryKey: ["pipeline", "board"] });
            break;
          case "document_accepted":
          case "document_rejected":
          case "docs_complete_for_plan":
            void queryClient.invalidateQueries({ queryKey: ["customers"] });
            break;
          case "bot_paused":
          case "human_handoff_requested":
            void queryClient.invalidateQueries({ queryKey: ["handoffs"] });
            break;
          default:
            break;
        }
      }
    },
    [queryClient],
  );

  const onOpen = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    void queryClient.invalidateQueries({ queryKey: ["handoffs"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }, [queryClient]);

  useWebSocket<ConversationEvent>({
    path: tenantId ? `/ws/tenants/${tenantId}` : "",
    onEvent,
    onOpen,
    enabled: !!tenantId,
  });
}

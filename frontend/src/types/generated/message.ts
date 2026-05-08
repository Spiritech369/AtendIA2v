// AUTO-GENERATED — do not edit. Run `pnpm types` to regenerate.
// Source: contracts/*.schema.json

/**
 * A message exchanged in a conversation, inbound or outbound.
 */
export interface Message {
  id: string;
  conversation_id: string;
  tenant_id: string;
  direction: "inbound" | "outbound" | "system";
  text: string;
  sent_at: string;
  channel_message_id?: string | null;
  delivery_status?: null | "queued" | "sent" | "delivered" | "read" | "failed";
  metadata?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}

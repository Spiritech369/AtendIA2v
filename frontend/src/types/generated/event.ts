// AUTO-GENERATED — do not edit. Run `pnpm types` to regenerate.
// Source: contracts/*.schema.json

export interface Event {
  id: string;
  conversation_id: string;
  tenant_id: string;
  type:
    | "message_received"
    | "message_sent"
    | "stage_entered"
    | "stage_exited"
    | "field_extracted"
    | "tool_called"
    | "human_handoff_requested"
    | "followup_scheduled"
    | "error_occurred";
  payload: {
    [k: string]: unknown;
  };
  occurred_at: string;
  trace_id?: string | null;
  [k: string]: unknown;
}

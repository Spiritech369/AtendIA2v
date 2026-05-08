// AUTO-GENERATED — do not edit. Run `pnpm types` to regenerate.
// Source: contracts/*.schema.json

export interface ConversationState {
  conversation_id: string;
  tenant_id: string;
  current_stage: string;
  extracted_data: {
    [k: string]: ExtractedField;
  };
  pending_confirmation?: string | null;
  last_intent?: string | null;
  stage_entered_at: string;
  followups_sent_count: number;
  total_cost_usd: string;
  [k: string]: unknown;
}
export interface ExtractedField {
  value: unknown;
  confidence: number;
  source_turn: number;
  [k: string]: unknown;
}

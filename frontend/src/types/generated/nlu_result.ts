// AUTO-GENERATED — do not edit. Run `pnpm types` to regenerate.
// Source: contracts/*.schema.json

export interface NLUResult {
  intent:
    | "greeting"
    | "ask_info"
    | "ask_price"
    | "buy"
    | "schedule"
    | "complain"
    | "off_topic"
    | "unclear";
  entities: {
    [k: string]: unknown;
  };
  sentiment: "positive" | "neutral" | "negative";
  confidence: number;
  ambiguities: string[];
  [k: string]: unknown;
}

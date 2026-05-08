// AUTO-GENERATED — do not edit. Run `pnpm types` to regenerate.
// Source: contracts/*.schema.json

export type FieldSpec =
  | string
  | {
      name: string;
      description?: string;
      [k: string]: unknown;
    };

export interface PipelineDefinition {
  version: number;
  nlu?: NLUConfig;
  composer?: ComposerConfig;
  /**
   * @minItems 1
   */
  stages: [StageDefinition, ...StageDefinition[]];
  fallback: string;
  [k: string]: unknown;
}
export interface NLUConfig {
  history_turns?: number;
  [k: string]: unknown;
}
export interface ComposerConfig {
  history_turns?: number;
  [k: string]: unknown;
}
export interface StageDefinition {
  id: string;
  required_fields?: FieldSpec[];
  optional_fields?: FieldSpec[];
  actions_allowed: string[];
  transitions: Transition[];
  timeout_hours?: number | null;
  timeout_action?: string | null;
  [k: string]: unknown;
}
export interface Transition {
  to: string;
  when: string;
  [k: string]: unknown;
}

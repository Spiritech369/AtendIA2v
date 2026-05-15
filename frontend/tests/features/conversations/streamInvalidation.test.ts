import { describe, expect, it } from "vitest";

import { affectsFieldSuggestions } from "@/features/conversations/lib/streamInvalidation";

describe("affectsFieldSuggestions (C11)", () => {
  it("is true for events that can produce new field suggestions", () => {
    // message_received is the realtime carrier: a SUGGEST-tier
    // suggestion is created during the inbound turn that emits it.
    expect(affectsFieldSuggestions("message_received")).toBe(true);
    expect(affectsFieldSuggestions("field_extracted")).toBe(true);
    expect(affectsFieldSuggestions("field_updated")).toBe(true);
  });

  it("is false for unrelated events", () => {
    expect(affectsFieldSuggestions("stage_changed")).toBe(false);
    expect(affectsFieldSuggestions("bot_paused")).toBe(false);
    expect(affectsFieldSuggestions("pipeline_updated")).toBe(false);
    expect(affectsFieldSuggestions("")).toBe(false);
  });
});

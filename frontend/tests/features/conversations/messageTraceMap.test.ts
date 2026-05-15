import { describe, expect, it } from "vitest";

import { buildMessageTraceMap } from "@/features/conversations/lib/messageTraceMap";

type M = { id: string; created_at: string };
type T = {
  id: string;
  inbound_message_id: string | null;
  turn_number: number;
  created_at: string;
};

function msg(id: string, t: string): M {
  return { id, created_at: `2026-05-15T00:00:${t}Z` };
}

describe("buildMessageTraceMap", () => {
  it("maps a turn's inbound + bot reply(s) to the same trace", () => {
    const messages: M[] = [msg("in1", "01"), msg("out1", "02"), msg("sys1", "03")];
    const traces: T[] = [
      { id: "tr1", inbound_message_id: "in1", turn_number: 1, created_at: "2026-05-15T00:00:01Z" },
    ];
    const map = buildMessageTraceMap(traces, messages);
    expect(map.get("in1")).toBe("tr1");
    expect(map.get("out1")).toBe("tr1"); // the "why did the agent say X" link
    expect(map.get("sys1")).toBe("tr1");
  });

  it("attributes each turn's messages to its own trace across turns", () => {
    const messages: M[] = [
      msg("in1", "01"),
      msg("out1", "02"),
      msg("in2", "03"),
      msg("out2", "04"),
    ];
    const traces: T[] = [
      { id: "trB", inbound_message_id: "in2", turn_number: 2, created_at: "2026-05-15T00:00:03Z" },
      { id: "trA", inbound_message_id: "in1", turn_number: 1, created_at: "2026-05-15T00:00:01Z" },
    ];
    const map = buildMessageTraceMap(traces, messages);
    expect(map.get("in1")).toBe("trA");
    expect(map.get("out1")).toBe("trA");
    expect(map.get("in2")).toBe("trB");
    expect(map.get("out2")).toBe("trB");
  });

  it("leaves messages before the first turn unmapped", () => {
    const messages: M[] = [msg("pre", "01"), msg("in1", "02"), msg("out1", "03")];
    const traces: T[] = [
      { id: "tr1", inbound_message_id: "in1", turn_number: 1, created_at: "2026-05-15T00:00:02Z" },
    ];
    const map = buildMessageTraceMap(traces, messages);
    expect(map.has("pre")).toBe(false);
    expect(map.get("out1")).toBe("tr1");
  });

  it("ignores traces with no inbound message anchor", () => {
    const messages: M[] = [msg("out1", "02")];
    const traces: T[] = [
      { id: "tr1", inbound_message_id: null, turn_number: 1, created_at: "2026-05-15T00:00:01Z" },
    ];
    const map = buildMessageTraceMap(traces, messages);
    expect(map.size).toBe(0);
  });

  it("is robust to unordered input", () => {
    const messages: M[] = [msg("out2", "04"), msg("in1", "01"), msg("out1", "02"), msg("in2", "03")];
    const traces: T[] = [
      { id: "trA", inbound_message_id: "in1", turn_number: 1, created_at: "2026-05-15T00:00:01Z" },
      { id: "trB", inbound_message_id: "in2", turn_number: 2, created_at: "2026-05-15T00:00:03Z" },
    ];
    const map = buildMessageTraceMap(traces, messages);
    expect(map.get("out1")).toBe("trA");
    expect(map.get("out2")).toBe("trB");
  });
});

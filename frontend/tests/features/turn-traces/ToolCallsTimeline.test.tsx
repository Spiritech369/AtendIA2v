import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { ToolCallsTimeline } from "@/features/turn-traces/components/TurnPanels";

function traceWithCalls(calls: unknown[]): TurnTraceDetail {
  return { tool_calls: calls } as unknown as TurnTraceDetail;
}

describe("ToolCallsTimeline", () => {
  it("renders one row per tool call with name + latency", () => {
    const trace = traceWithCalls([
      {
        id: "1",
        tool_name: "search_catalog",
        latency_ms: 421,
        input_payload: { query: "moto" },
        output_payload: { hits: 3 },
        error: null,
      },
      {
        id: "2",
        tool_name: "lookup_faq",
        latency_ms: 213,
        input_payload: { query: "horario" },
        output_payload: null,
        error: "no match",
      },
    ]);
    render(<ToolCallsTimeline trace={trace} />);
    expect(screen.getByText(/search_catalog/)).toBeInTheDocument();
    expect(screen.getByText(/421ms/)).toBeInTheDocument();
    expect(screen.getByText(/lookup_faq/)).toBeInTheDocument();
    expect(screen.getByText(/no match/i)).toBeInTheDocument();
  });

  it("renders an 'ok' badge on success and 'error' on failure", () => {
    const trace = traceWithCalls([
      {
        id: "1",
        tool_name: "x",
        latency_ms: 50,
        input_payload: {},
        output_payload: { ok: true },
        error: null,
      },
      {
        id: "2",
        tool_name: "y",
        latency_ms: 50,
        input_payload: {},
        output_payload: null,
        error: "boom",
      },
    ]);
    render(<ToolCallsTimeline trace={trace} />);
    expect(screen.getByText(/^ok$/i)).toBeInTheDocument();
    expect(screen.getByText(/^error$/i)).toBeInTheDocument();
  });

  it("renders empty state when no tool calls", () => {
    render(<ToolCallsTimeline trace={traceWithCalls([])} />);
    expect(screen.getByText(/sin herramientas/i)).toBeInTheDocument();
  });

  it("renders empty state when tool_calls is null/undefined", () => {
    render(<ToolCallsTimeline trace={{ tool_calls: null } as unknown as TurnTraceDetail} />);
    expect(screen.getByText(/sin herramientas/i)).toBeInTheDocument();
  });
});

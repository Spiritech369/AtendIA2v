import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { LatencyPerStepBar } from "@/features/turn-traces/components/TurnPanels";

function traceWithLatencies(overrides: Partial<TurnTraceDetail>): TurnTraceDetail {
  return {
    nlu_latency_ms: null,
    vision_latency_ms: null,
    composer_latency_ms: null,
    tool_calls: [],
    total_latency_ms: null,
    ...overrides,
  } as unknown as TurnTraceDetail;
}

describe("LatencyPerStepBar", () => {
  it("renders one row per non-zero slice + an Overhead row", () => {
    const trace = traceWithLatencies({
      nlu_latency_ms: 342,
      vision_latency_ms: 0,
      composer_latency_ms: 1820,
      tool_calls: [{ latency_ms: 210 } as any, { latency_ms: 211 } as any],
      total_latency_ms: 2847,
    });
    render(<LatencyPerStepBar trace={trace} />);
    expect(screen.getByText(/NLU/i)).toBeInTheDocument();
    expect(screen.getByText(/Composer/i)).toBeInTheDocument();
    expect(screen.getByText(/Tools/i)).toBeInTheDocument();
    expect(screen.getByText(/Overhead/i)).toBeInTheDocument();
    // Vision is 0 → omitted (no clutter for absent steps)
    expect(screen.queryByText(/Vision/i)).not.toBeInTheDocument();
  });

  it("renders null when no slices are present (legacy / empty)", () => {
    const { container } = render(<LatencyPerStepBar trace={traceWithLatencies({})} />);
    expect(container.firstChild).toBeNull();
  });

  it("omits Overhead when total equals sum of tracked slices", () => {
    const trace = traceWithLatencies({
      nlu_latency_ms: 100,
      composer_latency_ms: 200,
      tool_calls: [],
      total_latency_ms: 300, // exactly matches NLU + Composer
    });
    render(<LatencyPerStepBar trace={trace} />);
    expect(screen.queryByText(/Overhead/i)).not.toBeInTheDocument();
  });
});

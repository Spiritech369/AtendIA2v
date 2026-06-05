import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { dinamoShadowRealReplayTrace } from "@/features/turn-traces/__fixtures__/dinamoShadowRealReplayTrace";
import { dinamoShadowLatestUniversalTrace } from "@/features/turn-traces/__fixtures__/dinamoShadowUniversalTrace";
import type { TurnTraceDetail } from "@/features/turn-traces/api";
import { UniversalTracePanel } from "@/features/turn-traces/components/UniversalTracePanel";
import { readUniversalTurnTrace } from "@/features/turn-traces/lib/universalTrace";
import {
  appointmentUniversalTrace,
  vehicleUniversalTrace,
} from "../../fixtures/universalTurnTrace";

describe("UniversalTracePanel", () => {
  it("shows GPT proposed versus AtendIA validated state", () => {
    render(<UniversalTracePanel trace={vehicleUniversalTrace} />);

    expect(screen.getByText("Decision timeline")).toBeInTheDocument();
    expect(screen.getByText(/GPT propuso 2 cambio/)).toBeInTheDocument();
    expect(screen.getAllByText("StateWriter").length).toBeGreaterThan(0);
    expect(screen.getByText("accepted")).toBeInTheDocument();
    expect(screen.getAllByText("blocked").length).toBeGreaterThan(0);
    expect(screen.getByText("invalidated")).toBeInTheDocument();
  });

  it("shows a missing mandatory tool card", () => {
    render(<UniversalTracePanel trace={vehicleUniversalTrace} />);

    expect(screen.getByText("quote.resolve")).toBeInTheDocument();
    expect(screen.getByText("obligatoria")).toBeInTheDocument();
    expect(screen.getAllByText("missing").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/final_message/).length).toBeGreaterThan(0);
  });

  it("shows blocked guard and suggested next step", () => {
    render(<UniversalTracePanel trace={vehicleUniversalTrace} />);

    expect(screen.getByText("quote_safety")).toBeInTheDocument();
    expect(screen.getAllByText("blocked").length).toBeGreaterThan(0);
    expect(screen.getByText(/ejecutar quote.resolve/)).toBeInTheDocument();
  });

  it("uses final_output.final_message as customer visible response", () => {
    render(<UniversalTracePanel trace={vehicleUniversalTrace} />);

    expect(
      screen.getAllByText("Necesito confirmar la cotizacion del sistema antes de darte precio.")
        .length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/TurnOutput.final_message/)).toBeInTheDocument();
  });

  it("shows appointment trace without vehicle fields", () => {
    render(<UniversalTracePanel trace={appointmentUniversalTrace} />);

    expect(screen.getByText("appointment_services")).toBeInTheDocument();
    expect(screen.getByText("availability.check")).toBeInTheDocument();
    expect(screen.getAllByText("appointment_requested").length).toBeGreaterThan(0);
    expect(screen.queryByText("product_selection")).not.toBeInTheDocument();
    expect(screen.queryByText("plan_selection")).not.toBeInTheDocument();
    expect(screen.queryByText("quote_snapshot_id")).not.toBeInTheDocument();
  });

  it("renders Dinamo shadow universal trace with dry-run business events", () => {
    render(<UniversalTracePanel trace={dinamoShadowLatestUniversalTrace} />);

    expect(screen.getAllByText("vehicle_credit_sales").length).toBeGreaterThan(0);
    expect(screen.getAllByText("requirements_complete").length).toBeGreaterThan(0);
    expect(screen.getAllByText("human_handoff_requested").length).toBeGreaterThan(0);
    expect(screen.getAllByText("dry-run").length).toBeGreaterThan(0);
    expect(screen.getByText(/revision humana/)).toBeInTheDocument();
  });

  it("renders anonymized Dinamo real replay trace without PII", () => {
    render(<UniversalTracePanel trace={dinamoShadowRealReplayTrace} />);

    expect(screen.getAllByText("vehicle_credit_sales").length).toBeGreaterThan(0);
    expect(screen.getAllByText("dry-run").length).toBeGreaterThan(0);
    expect(screen.getAllByText("accepted").length).toBeGreaterThan(0);
    expect(screen.getAllByText("blocked").length).toBeGreaterThan(0);
    expect(screen.getByText(/Real replay shadow/)).toBeInTheDocument();
    expect(screen.getAllByText(/TurnOutput\.final_message/).length).toBeGreaterThan(0);

    const serialized = JSON.stringify(dinamoShadowRealReplayTrace);
    expect(serialized).not.toMatch(/\+?\d[\d\s().-]{7,}\d/);
    expect(serialized).not.toMatch(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/);
    expect(serialized).not.toContain("raw_customer_text");
  });

  it("reads universal trace from the real API trace_metadata shape", () => {
    const apiTrace = {
      trace_metadata: {
        universal_turn_trace: appointmentUniversalTrace,
      },
      composer_output: {
        trace_metadata: {
          universal_turn_trace: vehicleUniversalTrace,
        },
      },
      state_after: {
        trace_metadata: {
          universal_turn_trace: vehicleUniversalTrace,
        },
      },
    } as unknown as TurnTraceDetail;

    const trace = readUniversalTurnTrace(apiTrace);

    expect(trace?.domain).toBe("appointment_services");
    render(<UniversalTracePanel trace={trace} />);

    expect(screen.getByText("appointment_services")).toBeInTheDocument();
    expect(
      screen.getByText("Perfecto, tengo disponibilidad para ese horario."),
    ).toBeInTheDocument();
    expect(screen.queryByText("quote.resolve")).not.toBeInTheDocument();
  });

  it("shows metadata_missing fallback while raw trace remains in the legacy panel", () => {
    const legacyApiTrace = {
      composer_output: { messages: ["legacy raw output"] },
      state_after: { raw_trace_available: true },
    } as unknown as TurnTraceDetail;

    render(<UniversalTracePanel trace={readUniversalTurnTrace(legacyApiTrace)} />);

    expect(screen.getByText("metadata_missing")).toBeInTheDocument();
    expect(screen.getByText(/raw JSON/)).toBeInTheDocument();
  });
});

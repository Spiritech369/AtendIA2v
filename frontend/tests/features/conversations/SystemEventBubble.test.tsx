import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  SystemEventBubble,
  hasStructuredSystemEvent,
} from "@/features/conversations/components/SystemEventBubble";

describe("hasStructuredSystemEvent", () => {
  it("returns true when metadata.event_type is a string", () => {
    expect(hasStructuredSystemEvent({ event_type: "stage_changed" })).toBe(true);
  });

  it("returns false for legacy system messages with no metadata", () => {
    expect(hasStructuredSystemEvent(null)).toBe(false);
    expect(hasStructuredSystemEvent(undefined)).toBe(false);
    expect(hasStructuredSystemEvent({})).toBe(false);
  });

  it("returns false when event_type is not a string", () => {
    expect(hasStructuredSystemEvent({ event_type: 42 })).toBe(false);
  });
});

describe("SystemEventBubble", () => {
  it("renders the localized text", () => {
    render(
      <SystemEventBubble
        text="Sistema: Plan de crédito actualizado a Nómina Tarjeta 10%"
        metadata={{
          event_type: "field_updated",
          payload: { field: "plan_credito", new_value: "Nómina Tarjeta 10%" },
        }}
      />,
    );
    expect(
      screen.getByText(/Plan de crédito actualizado a Nómina Tarjeta 10%/),
    ).toBeInTheDocument();
  });

  it("sets data-event-type so styling/automated tests can discriminate", () => {
    const { container } = render(
      <SystemEventBubble
        text="Sistema: Conversación movida a Papelería incompleta"
        metadata={{
          event_type: "stage_changed",
          payload: {
            from: "nuevo",
            to: "papeleria_incompleta",
            from_label: "Nuevo",
            to_label: "Papelería incompleta",
          },
        }}
      />,
    );
    const pill = container.querySelector("[data-event-type]");
    expect(pill).not.toBeNull();
    expect(pill?.getAttribute("data-event-type")).toBe("stage_changed");
  });

  it("falls back to the default variant when event_type is unknown", () => {
    const { container } = render(
      <SystemEventBubble
        text="Sistema: evento desconocido"
        metadata={{ event_type: "some_future_event_we_dont_handle_yet" }}
      />,
    );
    expect(
      container.querySelector("[data-event-type]")?.getAttribute("data-event-type"),
    ).toBe("default");
  });

  it("shows rejection reason as secondary detail for rejected docs", () => {
    render(
      <SystemEventBubble
        text="Sistema: Documento rechazado — INE"
        metadata={{
          event_type: "document_rejected",
          payload: {
            document_type: "ine",
            confidence: 0.4,
            reason: "ilegible por reflejo",
          },
        }}
      />,
    );
    expect(screen.getByText("ilegible por reflejo")).toBeInTheDocument();
  });

  it("shows old → new + confidence for field_updated", () => {
    render(
      <SystemEventBubble
        text="Sistema: Plan de crédito actualizado a 15"
        metadata={{
          event_type: "field_updated",
          payload: {
            field: "plan_credito",
            old_value: "10",
            new_value: "15",
            confidence: 0.92,
            source: "nlu",
          },
        }}
      />,
    );
    // Both halves of the transition show, plus confidence.
    expect(screen.getByText(/10 → 15.*conf 92%/)).toBeInTheDocument();
  });

  it("renders without crashing when metadata is null", () => {
    const { container } = render(
      <SystemEventBubble text="Sistema: legacy" metadata={null} />,
    );
    expect(container.textContent).toContain("Sistema: legacy");
  });
});

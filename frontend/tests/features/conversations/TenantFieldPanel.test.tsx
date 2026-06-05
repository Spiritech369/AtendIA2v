import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TenantFieldPanel } from "@/features/conversations/components/TenantFieldPanel";
import { normalizeTenantFields } from "@/features/turn-traces/lib/universalTrace";
import { appointmentFields, vehicleCreditFields } from "../../fixtures/universalTurnTrace";

describe("TenantFieldPanel", () => {
  it("renders vehicle credit fields from metadata", () => {
    render(<TenantFieldPanel fields={normalizeTenantFields(vehicleCreditFields)} />);

    expect(screen.getByText("Moto seleccionada")).toBeInTheDocument();
    expect(screen.getByText("R4 250 CC")).toBeInTheDocument();
    expect(screen.getByText("Plan de credito")).toBeInTheDocument();
    expect(screen.getByText("Papeleria completa")).toBeInTheDocument();
    expect(screen.getByText("Buro mencionado")).toBeInTheDocument();
    expect(screen.getByText("Handoff")).toBeInTheDocument();
  });

  it("renders appointment fields and does not show vehicle credit fields", () => {
    render(<TenantFieldPanel fields={normalizeTenantFields(appointmentFields)} />);

    expect(screen.getByText("Servicio")).toBeInTheDocument();
    expect(screen.getByText("Corte clasico")).toBeInTheDocument();
    expect(screen.getByText("Horario")).toBeInTheDocument();
    expect(screen.getByText("Estado de cita")).toBeInTheDocument();
    expect(screen.queryByText("Moto seleccionada")).not.toBeInTheDocument();
    expect(screen.queryByText("Plan de credito")).not.toBeInTheDocument();
    expect(screen.queryByText("Papeleria completa")).not.toBeInTheDocument();
  });

  it("does not show proposed or blocked fields as validated", () => {
    render(<TenantFieldPanel fields={normalizeTenantFields(appointmentFields)} />);

    expect(screen.getByText("needs_review")).toBeInTheDocument();
    expect(screen.getByText("blocked")).toBeInTheDocument();
    expect(screen.getAllByText("validated")).toHaveLength(1);
  });

  it("shows safe mode and missing metadata badges", () => {
    render(<TenantFieldPanel fields={[]} safeMode metadataMissing />);

    expect(screen.getByText("safe_mode")).toBeInTheDocument();
    expect(screen.getByText("metadata_missing")).toBeInTheDocument();
  });
});

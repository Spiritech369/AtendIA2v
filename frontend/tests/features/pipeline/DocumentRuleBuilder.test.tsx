import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  type DocumentCatalogEntry,
  DocumentRuleBuilder,
} from "@/features/pipeline/components/DocumentRuleBuilder";
import type { AutoEnterRulesDraft } from "@/features/pipeline/components/PipelineEditor";

// Shared catalog fixture. Mirrors the labels/keys the existing
// assertions hard-code so tests behave identically to before the
// catalog became a required prop.
const CATALOG_FIXTURE: ReadonlyArray<DocumentCatalogEntry> = [
  { key: "DOCS_INE", label: "INE" },
  { key: "DOCS_COMPROBANTE_DOMICILIO", label: "Comprobante de domicilio" },
  { key: "DOCS_ESTADOS_CUENTA", label: "Estados de cuenta" },
  { key: "DOCS_RECIBOS_NOMINA", label: "Recibos de nómina" },
  { key: "DOCS_RESOLUCION_IMSS", label: "Resolución IMSS" },
];

describe("DocumentRuleBuilder", () => {
  it("renders one button per catalog entry", () => {
    render(
      <DocumentRuleBuilder
        stageLabel="Papelería completa"
        rules={undefined}
        catalog={CATALOG_FIXTURE}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("INE")).toBeInTheDocument();
    expect(screen.getByText("Comprobante de domicilio")).toBeInTheDocument();
    expect(screen.getByText("Estados de cuenta")).toBeInTheDocument();
    expect(screen.getByText("Recibos de nómina")).toBeInTheDocument();
    expect(screen.getByText("Resolución IMSS")).toBeInTheDocument();
  });

  it("clicking an unchecked doc emits an enabled rule with one condition", () => {
    const onChange = vi.fn();
    render(
      <DocumentRuleBuilder
        stageLabel="Papelería completa"
        rules={undefined}
        catalog={CATALOG_FIXTURE}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByText("INE"));
    expect(onChange).toHaveBeenCalledWith({
      enabled: true,
      match: "all",
      conditions: [{ field: "DOCS_INE.status", operator: "equals", value: "ok" }],
    });
  });

  it("pre-fills the checklist when the stage already has doc-shaped rules", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [
        { field: "DOCS_INE.status", operator: "equals", value: "ok" },
        { field: "DOCS_RECIBOS_NOMINA.status", operator: "equals", value: "ok" },
      ],
    };
    render(
      <DocumentRuleBuilder
        stageLabel="X"
        rules={rules}
        catalog={CATALOG_FIXTURE}
        onChange={() => {}}
      />,
    );
    // The two pre-checked buttons should report aria-pressed=true
    const inePressed = screen.getByText("INE").closest("button");
    const nominaPressed = screen.getByText("Recibos de nómina").closest("button");
    expect(inePressed).toHaveAttribute("aria-pressed", "true");
    expect(nominaPressed).toHaveAttribute("aria-pressed", "true");
    // And one that wasn't selected is aria-pressed=false
    const imssPressed = screen.getByText("Resolución IMSS").closest("button");
    expect(imssPressed).toHaveAttribute("aria-pressed", "false");
  });

  it("unchecking the last selected doc collapses rules to undefined", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [{ field: "DOCS_INE.status", operator: "equals", value: "ok" }],
    };
    const onChange = vi.fn();
    render(
      <DocumentRuleBuilder
        stageLabel="X"
        rules={rules}
        catalog={CATALOG_FIXTURE}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByText("INE"));
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("Limpiar button clears all selections", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [{ field: "DOCS_INE.status", operator: "equals", value: "ok" }],
    };
    const onChange = vi.fn();
    render(
      <DocumentRuleBuilder
        stageLabel="X"
        rules={rules}
        catalog={CATALOG_FIXTURE}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /limpiar/i }));
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("locks read-only when the stage has non-doc conditions", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [
        // Not a DOCS_*.status equals "ok" condition
        { field: "modelo_interes", operator: "exists" },
      ],
    };
    render(
      <DocumentRuleBuilder
        stageLabel="X"
        rules={rules}
        catalog={CATALOG_FIXTURE}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/reglas personalizadas activas/i)).toBeInTheDocument();
    // No checklist rendered
    expect(screen.queryByText("INE")).not.toBeInTheDocument();
  });

  it("locks read-only when the doc condition uses an unexpected value", () => {
    /** A rule that uses DOCS_INE.status but operator != equals "ok" is
     *  "doc-shaped on the surface but semantically different" — the
     *  checklist would lie if it claimed to represent it. Lock and
     *  redirect to RuleBuilder. */
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [{ field: "DOCS_INE.status", operator: "not_equals", value: "missing" }],
    };
    render(
      <DocumentRuleBuilder
        stageLabel="X"
        rules={rules}
        catalog={CATALOG_FIXTURE}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/reglas personalizadas activas/i)).toBeInTheDocument();
  });

  it("disabled prop greys out all buttons", () => {
    render(
      <DocumentRuleBuilder
        stageLabel="X"
        rules={undefined}
        catalog={CATALOG_FIXTURE}
        onChange={() => {}}
        disabled
      />,
    );
    const buttons = screen.getAllByRole("button");
    // Every doc card should be disabled
    for (const btn of buttons) expect(btn).toBeDisabled();
  });
});

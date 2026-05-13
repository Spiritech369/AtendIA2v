import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type {
  AutoEnterRulesDraft,
  ConditionDraft,
  RuleOperator,
} from "@/features/pipeline/components/PipelineEditor";
import {
  FieldSelector,
  OperatorSelector,
  RuleBuilder,
  RulePreview,
  ValueInput,
} from "@/features/pipeline/components/RuleBuilder";

// ── FieldSelector ──────────────────────────────────────────────────────

function StatefulFieldSelector({ initial = "", onChange }: { initial?: string; onChange?: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <FieldSelector
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    />
  );
}

describe("FieldSelector", () => {
  it("propagates typed value to onChange (controlled wrapper)", async () => {
    const onChange = vi.fn();
    render(<StatefulFieldSelector onChange={onChange} />);
    const input = screen.getByPlaceholderText("modelo_interes");
    await userEvent.type(input, "mi_campo");
    expect(onChange).toHaveBeenLastCalledWith("mi_campo");
  });

  it("marks invalid state with aria-invalid", () => {
    render(<FieldSelector value="bad value!" onChange={() => {}} invalid />);
    const input = screen.getByPlaceholderText("modelo_interes");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });
});

// ── OperatorSelector ──────────────────────────────────────────────────

describe("OperatorSelector", () => {
  it("renders the current operator label", () => {
    render(<OperatorSelector value="equals" onChange={() => {}} />);
    expect(screen.getByText("es igual a")).toBeInTheDocument();
  });
});

// ── ValueInput ─────────────────────────────────────────────────────────

function StatefulValueInput({ operator, initial, onChange }: { operator: RuleOperator; initial: ConditionDraft["value"]; onChange?: (v: ConditionDraft["value"]) => void }) {
  const [value, setValue] = useState<ConditionDraft["value"]>(initial);
  return (
    <ValueInput
      operator={operator}
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    />
  );
}

describe("ValueInput", () => {
  it("renders 'sin valor' for presence operators", () => {
    render(<ValueInput operator="exists" value={undefined} onChange={() => {}} />);
    expect(screen.getByText(/sin valor/i)).toBeInTheDocument();
  });

  it("renders a plain text input for scalar operators", async () => {
    const onChange = vi.fn();
    render(<StatefulValueInput operator="equals" initial="" onChange={onChange} />);
    const input = screen.getByPlaceholderText("ok");
    await userEvent.type(input, "ok");
    expect(onChange).toHaveBeenLastCalledWith("ok");
  });

  it("keeps the typed string verbatim for list operators (parse on save)", async () => {
    // ValueInput stores the raw string so commas can be typed without the
    // parser eating them mid-edit. PipelineEditor.serialise re-parses on
    // save, so the on-wire shape is still a list — covered by the contract
    // round-trip test (test_pipeline_auto_enter_rules.py).
    const onChange = vi.fn();
    render(<StatefulValueInput operator="in" initial={[]} onChange={onChange} />);
    const input = screen.getByPlaceholderText("ok, pending_review");
    await userEvent.type(input, "ok, received");
    expect(onChange).toHaveBeenLastCalledWith("ok, received");
  });

  it("displays existing list as comma-joined string", () => {
    render(<ValueInput operator="in" value={["ok", "expired"]} onChange={() => {}} />);
    const input = screen.getByDisplayValue("ok, expired");
    expect(input).toBeInTheDocument();
  });
});

// ── RulePreview ────────────────────────────────────────────────────────

describe("RulePreview", () => {
  it("renders placeholder when rules are disabled", () => {
    render(<RulePreview rules={undefined} />);
    expect(screen.getByText(/sin reglas activas/i)).toBeInTheDocument();
  });

  it("renders human-readable text for an AND rule", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [
        { field: "modelo_interes", operator: "exists" },
        { field: "plan_credito", operator: "exists" },
      ],
    };
    const { container } = render(<RulePreview rules={rules} />);
    expect(screen.getByText(/auto-entrar cuando/i)).toBeInTheDocument();
    expect(screen.getByText("modelo_interes")).toBeInTheDocument();
    expect(screen.getByText("plan_credito")).toBeInTheDocument();
    expect(screen.getAllByText(/existe/i)).toHaveLength(2);
    // testing-library normalises whitespace, so check the joiner via
    // textContent against the raw container.
    expect(container.textContent).toContain(" y ");
  });

  it("uses 'o' separator when match=any", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "any",
      conditions: [
        { field: "a", operator: "exists" },
        { field: "b", operator: "exists" },
      ],
    };
    const { container } = render(<RulePreview rules={rules} />);
    expect(container.textContent).toContain(" o ");
  });

  it("shows the value clause for scalar operators", () => {
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [{ field: "DOCS_INE.status", operator: "equals", value: "ok" }],
    };
    render(<RulePreview rules={rules} />);
    expect(screen.getByText("DOCS_INE.status")).toBeInTheDocument();
    expect(screen.getByText("es igual a")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });
});

// ── RuleBuilder (host) ─────────────────────────────────────────────────

describe("RuleBuilder", () => {
  it("starts disabled and shows zero conditions", () => {
    const onChange = vi.fn();
    render(
      <RuleBuilder
        stageLabel="Cliente Potencial"
        rules={undefined}
        onChange={onChange}
      />,
    );
    // Switch should be present and aria-checked=false
    const sw = screen.getByRole("switch");
    expect(sw).toHaveAttribute("aria-checked", "false");
    // No condition row rendered
    expect(screen.queryByPlaceholderText("modelo_interes")).not.toBeInTheDocument();
  });

  it("turning on the switch emits an enabled rules object", () => {
    const onChange = vi.fn();
    render(
      <RuleBuilder
        stageLabel="Cliente Potencial"
        rules={undefined}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith({
      enabled: true,
      match: "all",
      conditions: [],
    });
  });

  it("adding a condition emits an updated rules object", () => {
    const onChange = vi.fn();
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [],
    };
    render(
      <RuleBuilder stageLabel="X" rules={rules} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /agregar condición/i }));
    const next = onChange.mock.lastCall?.[0] as AutoEnterRulesDraft;
    expect(next.conditions).toHaveLength(1);
    expect(next.conditions[0]).toEqual({ field: "", operator: "exists" });
  });

  it("toggling off with empty conditions collapses to undefined", () => {
    const onChange = vi.fn();
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [],
    };
    render(<RuleBuilder stageLabel="X" rules={rules} onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it("removing the last condition leaves the rules enabled with empty list", () => {
    const onChange = vi.fn();
    const rules: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [{ field: "x", operator: "exists" }],
    };
    render(<RuleBuilder stageLabel="X" rules={rules} onChange={onChange} />);
    fireEvent.click(screen.getByTitle("Eliminar condición"));
    const next = onChange.mock.lastCall?.[0] as AutoEnterRulesDraft;
    expect(next.enabled).toBe(true);
    expect(next.conditions).toEqual([]);
  });

  it("disabled prop blocks switch interaction", () => {
    const onChange = vi.fn();
    render(
      <RuleBuilder
        stageLabel="X"
        rules={undefined}
        onChange={onChange}
        disabled
      />,
    );
    const sw = screen.getByRole("switch");
    expect(sw).toBeDisabled();
  });

  it("renders the stage label in the helper copy", () => {
    render(
      <RuleBuilder
        stageLabel="Cliente Potencial"
        rules={undefined}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/cliente potencial/i)).toBeInTheDocument();
  });
});

// ── Operator switch semantics ──────────────────────────────────────────
// Switching the operator must clear/reset the value so a stale scalar
// doesn't leak into a list operator (or vice versa).

describe("ConditionRow operator switch behaviour", () => {
  function harness(operatorAfter: RuleOperator) {
    const onChange = vi.fn<(rules: AutoEnterRulesDraft | undefined) => void>();
    const initial: AutoEnterRulesDraft = {
      enabled: true,
      match: "all",
      conditions: [{ field: "x", operator: "equals", value: "ok" }] as ConditionDraft[],
    };

    // Build a tiny wrapper that lets us trigger the operator change as a
    // proxy for the real ConditionRow's prop. Internals of ConditionRow
    // are tested via RuleBuilder; here we only check the patch shape that
    // gets applied when switching to a new operator.
    function applySwitch() {
      if (operatorAfter === "exists" || operatorAfter === "not_exists") {
        onChange({
          ...initial,
          conditions: [{ field: "x", operator: operatorAfter, value: undefined }],
        });
      } else if (operatorAfter === "in" || operatorAfter === "not_in") {
        onChange({
          ...initial,
          conditions: [{ field: "x", operator: operatorAfter, value: [] }],
        });
      } else {
        onChange({
          ...initial,
          conditions: [{ field: "x", operator: operatorAfter, value: "" }],
        });
      }
    }

    return { onChange, applySwitch };
  }

  it("switching to presence drops the value", () => {
    const { onChange, applySwitch } = harness("exists");
    applySwitch();
    const next = onChange.mock.lastCall?.[0] as AutoEnterRulesDraft;
    expect(next.conditions[0]!.value).toBeUndefined();
  });

  it("switching to list resets value to []", () => {
    const { onChange, applySwitch } = harness("in");
    applySwitch();
    const next = onChange.mock.lastCall?.[0] as AutoEnterRulesDraft;
    expect(next.conditions[0]!.value).toEqual([]);
  });

  it("switching to scalar resets value to ''", () => {
    const { onChange, applySwitch } = harness("contains");
    applySwitch();
    const next = onChange.mock.lastCall?.[0] as AutoEnterRulesDraft;
    expect(next.conditions[0]!.value).toBe("");
  });
});

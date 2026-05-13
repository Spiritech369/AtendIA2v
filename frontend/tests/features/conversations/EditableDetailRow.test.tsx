import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EditableDetailRow } from "@/features/conversations/components/EditableDetailRow";

describe("EditableDetailRow", () => {
  it("renders value in read mode", () => {
    render(
      <EditableDetailRow
        label="Etapa"
        value="Nuevo Lead"
        editable={false}
        deletable={false}
        onSave={() => {}}
      />,
    );
    expect(screen.getByText("Etapa")).toBeInTheDocument();
    expect(screen.getByText("Nuevo Lead")).toBeInTheDocument();
  });

  it("falls back to 'Sin dato' when value is null", () => {
    render(
      <EditableDetailRow label="Email" value={null} editable deletable={false} onSave={() => {}} />,
    );
    expect(screen.getByText("Sin dato")).toBeInTheDocument();
  });

  it("enters edit mode on pencil click and saves on Enter", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <EditableDetailRow
        label="Email"
        value="old@x.com"
        editable
        deletable={false}
        inputType="text"
        onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText("Editar Email"));
    const input = screen.getByDisplayValue("old@x.com") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "new@x.com");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledWith("new@x.com");
  });

  it("cancels on Escape without calling onSave", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<EditableDetailRow label="X" value="v" editable deletable={false} onSave={onSave} />);
    await user.click(screen.getByLabelText("Editar X"));
    const input = screen.getByDisplayValue("v");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders native select when inputType=select with options", async () => {
    const user = userEvent.setup();
    render(
      <EditableDetailRow
        label="Plan"
        value="10"
        editable
        deletable={false}
        inputType="select"
        options={[
          { value: "10", label: "10" },
          { value: "20", label: "20" },
        ]}
        onSave={() => {}}
      />,
    );
    await user.click(screen.getByLabelText("Editar Plan"));
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "10" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "20" })).toBeInTheDocument();
  });

  it("calls onDelete when delete button confirmed", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <EditableDetailRow
        label="Custom"
        value="abc"
        editable
        deletable
        onSave={() => {}}
        onDelete={onDelete}
      />,
    );
    await user.click(screen.getByLabelText("Eliminar Custom"));
    await user.click(screen.getByRole("button", { name: /confirmar/i }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("blocks save when validate returns an error message", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <EditableDetailRow
        label="Email"
        value="x@x.com"
        editable
        deletable={false}
        validate={(v) => (v.includes("@") ? null : "Email inválido")}
        onSave={onSave}
      />,
    );
    await user.click(screen.getByLabelText("Editar Email"));
    const input = screen.getByDisplayValue("x@x.com") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "not-an-email");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Email inválido")).toBeInTheDocument();
  });

  it("calls onSave with null when the input is cleared", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <EditableDetailRow label="X" value="something" editable deletable={false} onSave={onSave} />,
    );
    await user.click(screen.getByLabelText("Editar X"));
    const input = screen.getByDisplayValue("something") as HTMLInputElement;
    await user.clear(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledWith(null);
  });
});

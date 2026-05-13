import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AddCustomAttrDialog,
  slugify,
} from "@/features/conversations/components/AddCustomAttrDialog";

describe("slugify", () => {
  it("converts spaces to underscores", () => {
    expect(slugify("Color Favorito")).toBe("color_favorito");
  });
  it("strips diacritics", () => {
    expect(slugify("Año de Compra")).toBe("ano_de_compra");
  });
  it("collapses non-alphanumerics", () => {
    expect(slugify("Hola!! Mundo??")).toBe("hola_mundo");
  });
  it("trims leading/trailing underscores", () => {
    expect(slugify("  hola  ")).toBe("hola");
  });
});

describe("AddCustomAttrDialog", () => {
  it("auto-slugifies the key from the label", async () => {
    const user = userEvent.setup();
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={() => {}} />);
    const labelInput = screen.getByLabelText("Etiqueta");
    await user.type(labelInput, "Color Favorito");
    const keyInput = screen.getByLabelText("Clave") as HTMLInputElement;
    expect(keyInput.value).toBe("color_favorito");
  });

  it("allows manual key override that sticks despite later label changes", async () => {
    const user = userEvent.setup();
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={() => {}} />);
    const labelInput = screen.getByLabelText("Etiqueta");
    const keyInput = screen.getByLabelText("Clave") as HTMLInputElement;
    await user.type(labelInput, "Algo");
    await user.clear(keyInput);
    await user.type(keyInput, "custom_key");
    await user.type(labelInput, " mas");
    expect(keyInput.value).toBe("custom_key");
  });

  it("calls onSubmit with payload on save", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={onSubmit} />);
    await user.type(screen.getByLabelText("Etiqueta"), "Color");
    await user.type(screen.getByLabelText("Valor"), "Rojo");
    await user.click(screen.getByRole("button", { name: /guardar/i }));
    expect(onSubmit).toHaveBeenCalledWith({
      key: "color",
      label: "Color",
      value: "Rojo",
      field_type: "text",
    });
  });

  it("save button is disabled when key or value is empty", async () => {
    render(<AddCustomAttrDialog open onClose={() => {}} onSubmit={() => {}} />);
    const saveBtn = screen.getByRole("button", { name: /guardar/i });
    expect(saveBtn).toBeDisabled();
  });
});

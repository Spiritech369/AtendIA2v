import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessageItem } from "@/features/conversations/api";
import { MessageBubble } from "@/features/conversations/components/MessageBubble";

function msg(over: Partial<MessageItem> = {}): MessageItem {
  return {
    id: "m1",
    conversation_id: "c1",
    direction: "outbound",
    text: "hola cliente",
    metadata: {},
    created_at: "2026-05-15T00:00:00Z",
    sent_at: "2026-05-15T00:00:00Z",
    ...over,
  };
}

describe("MessageBubble edit/delete (C9)", () => {
  it("does not render edit/delete affordances without handlers", () => {
    render(<MessageBubble message={msg()} />);
    expect(screen.queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /eliminar/i })).not.toBeInTheDocument();
  });

  it("edits inline and calls onEdit with the new text", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    render(<MessageBubble message={msg()} onEdit={onEdit} onDelete={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    const box = screen.getByRole("textbox");
    await user.clear(box);
    await user.type(box, "texto corregido");
    await user.click(screen.getByRole("button", { name: /guardar/i }));

    expect(onEdit).toHaveBeenCalledWith("m1", "texto corregido");
  });

  it("cancel restores the original text without calling onEdit", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    render(<MessageBubble message={msg()} onEdit={onEdit} onDelete={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /editar/i }));
    await user.click(screen.getByRole("button", { name: /cancelar/i }));

    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.getByText("hola cliente")).toBeInTheDocument();
  });

  it("calls onDelete when the delete button is clicked", async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    render(<MessageBubble message={msg()} onEdit={vi.fn()} onDelete={onDelete} />);
    await user.click(screen.getByRole("button", { name: /eliminar/i }));
    expect(onDelete).toHaveBeenCalledWith("m1");
  });

  it("shows an 'editado' marker when the message was edited", () => {
    render(<MessageBubble message={msg({ edited_at: "2026-05-15T01:00:00Z" })} />);
    expect(screen.getByText(/editado/i)).toBeInTheDocument();
  });
});

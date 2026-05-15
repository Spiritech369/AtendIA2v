import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PublishConfirmDialog } from "@/features/agents/components/PublishConfirmDialog";

describe("PublishConfirmDialog", () => {
  it("renders nothing when closed", () => {
    render(
      <PublishConfirmDialog
        open={false}
        agentName="Vendedor"
        version="v3"
        pending={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByText(/publicar/i)).not.toBeInTheDocument();
  });

  it("shows the agent name, version and a production warning when open", () => {
    render(
      <PublishConfirmDialog
        open
        agentName="Vendedor"
        version="v3"
        pending={false}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText(/Vendedor/)).toBeInTheDocument();
    expect(screen.getByText(/v3/)).toBeInTheDocument();
    expect(screen.getByText(/clientes reales/i)).toBeInTheDocument();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <PublishConfirmDialog
        open
        agentName="Vendedor"
        version="v3"
        pending={false}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /publicar a producci[oó]n/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when the cancel button is clicked", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <PublishConfirmDialog
        open
        agentName="Vendedor"
        version="v3"
        pending={false}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    await user.click(screen.getByRole("button", { name: /cancelar/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables the confirm button while a publish is pending", () => {
    render(
      <PublishConfirmDialog
        open
        agentName="Vendedor"
        version="v3"
        pending
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: /publicando|publicar a producci[oó]n/i }),
    ).toBeDisabled();
  });
});

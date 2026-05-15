import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { agentsApi } from "@/features/agents/api";
import { AgentWorkflowRefs } from "@/features/agents/components/AgentWorkflowRefs";

const AGENT = "11111111-1111-1111-1111-111111111111";

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("agentsApi.workflowsUsing (W5)", () => {
  it("calls the reverse-dependency endpoint", async () => {
    const spy = vi.spyOn(agentsApi, "workflowsUsing").mockResolvedValue([]);
    await agentsApi.workflowsUsing(AGENT);
    expect(spy).toHaveBeenCalledWith(AGENT);
  });
});

describe("AgentWorkflowRefs", () => {
  it("shows an empty state when no workflow references the agent", async () => {
    vi.spyOn(agentsApi, "workflowsUsing").mockResolvedValue([]);
    render(<AgentWorkflowRefs agentId={AGENT} />, { wrapper: wrap() });
    await waitFor(() =>
      expect(screen.getByText(/ning[uú]n workflow/i)).toBeInTheDocument(),
    );
  });

  it("lists referencing workflows with their node count", async () => {
    vi.spyOn(agentsApi, "workflowsUsing").mockResolvedValue([
      { id: "wf-1", name: "Bienvenida", active: true, version: 2, node_ids: ["assign_1", "assign_2"] },
    ]);
    render(<AgentWorkflowRefs agentId={AGENT} />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText("Bienvenida")).toBeInTheDocument());
    expect(screen.getByText(/2 nodos/i)).toBeInTheDocument();
  });
});

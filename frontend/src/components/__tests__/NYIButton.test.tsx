import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useCapabilitiesStore } from "@/stores/capabilities";

import { NYIButton } from "../NYIButton";

describe("NYIButton", () => {
  beforeEach(() => {
    useCapabilitiesStore.getState().reset();
  });

  it("renders nothing when the capabilities flag is absent", () => {
    const { container } = render(<NYIButton label="Importar CSV" />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText("Importar CSV")).not.toBeInTheDocument();
  });

  it("renders with the given label when capabilities allow it", () => {
    useCapabilitiesStore.setState({
      capabilities: {
        schema_version: "test",
        tenant_id: "t1",
        feature_flags: {
          show_nyi_controls: true,
          demo_mode: false,
          mock_knowledge_model: false,
        },
        limits: { max_pipeline_stages: 30, max_workflow_nodes: 100 },
        current_user: { id: "u1", role: "operator", capabilities: [] },
      },
      status: "ready",
    });

    render(<NYIButton label="Importar CSV" />);

    expect(screen.getByText("Importar CSV")).toBeInTheDocument();
    expect(screen.getByTitle(/Feature en construcci/i)).toBeInTheDocument();
  });
});

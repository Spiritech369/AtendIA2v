import { describe, expect, it, vi } from "vitest";

import { workflowsApi } from "@/features/workflows/api";
import { api } from "@/lib/api-client";

describe("workflowsApi.exportExecutionsCsv (W16)", () => {
  it("requests the workflow executions CSV as a blob", async () => {
    const blob = new Blob(["execution_id\n"], { type: "text/csv" });
    const spy = vi.spyOn(api, "get").mockResolvedValue({ data: blob } as never);

    const result = await workflowsApi.exportExecutionsCsv("wf-1");

    expect(spy).toHaveBeenCalledWith("/workflows/wf-1/executions.csv", {
      responseType: "blob",
    });
    expect(result).toBe(blob);
  });
});

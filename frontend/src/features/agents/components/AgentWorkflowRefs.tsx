import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { agentsApi } from "@/features/agents/api";

/**
 * W5 — reverse dependency view. Answers "what automations break if I
 * disable/rename this agent" by listing the workflows whose
 * assign_agent nodes point at it.
 */
export function AgentWorkflowRefs({ agentId }: { agentId: string }) {
  const q = useQuery({
    queryKey: ["agent", agentId, "workflows-using"],
    queryFn: () => agentsApi.workflowsUsing(agentId),
    enabled: !!agentId,
  });

  return (
    <div className="rounded-lg border bg-card p-3 text-card-foreground">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold">Workflows que usan este agente</h3>
        {q.data && q.data.length > 0 && (
          <span className="text-[10px] text-muted-foreground">{q.data.length}</span>
        )}
      </div>
      {q.isLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : !q.data || q.data.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          Ningún workflow referencia este agente. Es seguro desactivarlo o
          renombrarlo sin romper automatizaciones.
        </p>
      ) : (
        <ul className="space-y-1">
          {q.data.map((wf) => (
            <li
              key={wf.id}
              className="flex items-center justify-between gap-2 rounded border px-2 py-1 text-xs"
            >
              <span className="min-w-0 flex-1 truncate font-medium">{wf.name}</span>
              <Badge
                variant={wf.active ? "outline" : "secondary"}
                className="shrink-0 text-[9px]"
              >
                {wf.active ? "activo" : "borrador"}
              </Badge>
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {wf.node_ids.length} {wf.node_ids.length === 1 ? "nodo" : "nodos"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

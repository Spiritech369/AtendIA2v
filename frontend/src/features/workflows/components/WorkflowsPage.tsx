import "@xyflow/react/dist/style.css";

import { Background, Controls, ReactFlow } from "@xyflow/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { workflowsApi, type WorkflowItem } from "@/features/workflows/api";

const TRIGGERS = ["message_received", "field_updated", "stage_changed", "appointment_created", "bot_paused"];
const ACTIONS = ["message", "move_stage", "assign_agent", "notify_agent", "update_field", "pause_bot", "delay", "condition"];

export function WorkflowsPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["workflows"], queryFn: workflowsApi.list });
  const [selected, setSelected] = useState<WorkflowItem | null>(null);
  const create = useMutation({
    mutationFn: workflowsApi.create,
    onSuccess: (wf) => {
      setSelected(wf);
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
  const remove = useMutation({
    mutationFn: workflowsApi.delete,
    onSuccess: () => {
      setSelected(null);
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
  const toggle = useMutation({
    mutationFn: workflowsApi.toggle,
    onSuccess: (wf) => {
      setSelected(wf);
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
  return (
    <div className="grid h-full gap-4 xl:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>Workflows</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button
            className="w-full"
            onClick={() =>
              create.mutate({
                name: "Nuevo workflow",
                trigger_type: "message_received",
                trigger_config: {},
                definition: { nodes: [{ id: "trigger_1", type: "trigger", config: {} }], edges: [] },
                active: false,
              })
            }
          >
            <Plus className="mr-2 h-4 w-4" /> Crear workflow
          </Button>
          {list.data?.map((wf) => (
            <button
              key={wf.id}
              type="button"
              onClick={() => setSelected(wf)}
              className={`w-full rounded-md border p-3 text-left text-sm ${selected?.id === wf.id ? "border-primary bg-muted" : ""}`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">{wf.name}</span>
                <Badge variant={wf.active ? "default" : "secondary"}>{wf.active ? "Activo" : "Pausado"}</Badge>
              </div>
              <div className="text-xs text-muted-foreground">{wf.trigger_type}</div>
            </button>
          ))}
        </CardContent>
      </Card>
      {selected ? (
        <WorkflowEditor
          workflow={selected}
          onDelete={() => remove.mutate(selected.id)}
          onToggle={() => toggle.mutate(selected.id)}
        />
      ) : (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">Selecciona o crea un workflow.</CardContent>
        </Card>
      )}
    </div>
  );
}

function WorkflowEditor({ workflow, onDelete, onToggle }: { workflow: WorkflowItem; onDelete: () => void; onToggle: () => void }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(workflow);
  const executions = useQuery({
    queryKey: ["workflows", workflow.id, "executions"],
    queryFn: () => workflowsApi.executions(workflow.id),
  });
  const save = useMutation({
    mutationFn: () => workflowsApi.patch(workflow.id, draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });
  const actions = useMemo(
    () => (draft.definition.nodes ?? []).filter((node) => node.type !== "trigger"),
    [draft.definition.nodes],
  );
  const setActions = (nextActions: Array<Record<string, unknown>>) => {
    const trigger = { id: "trigger_1", type: "trigger", config: { event: draft.trigger_type } };
    const nodes = [trigger, ...nextActions.map((action, index) => ({ ...action, id: `action_${index + 1}` }))];
    const edges = nodes.slice(1).map((node, index) => ({
      from: index === 0 ? "trigger_1" : `action_${index}`,
      to: node.id,
    }));
    setDraft((prev) => ({ ...prev, definition: { nodes, edges } }));
  };
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{draft.name}</CardTitle>
        <div className="flex gap-2">
          <Button variant={draft.active ? "secondary" : "default"} onClick={onToggle}>
            {draft.active ? "Pausar" : "Activar"}
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>Guardar</Button>
          <Button variant="ghost" size="icon" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="form">
          <TabsList>
            <TabsTrigger value="form">Editor</TabsTrigger>
            <TabsTrigger value="visual">Visual</TabsTrigger>
            <TabsTrigger value="json">JSON</TabsTrigger>
            <TabsTrigger value="runs">Ejecuciones</TabsTrigger>
          </TabsList>
          <TabsContent value="form" className="mt-4 space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <Label>Nombre</Label>
                <Input value={draft.name} onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))} />
              </div>
              <div>
                <Label>Trigger</Label>
                <Select value={draft.trigger_type} onValueChange={(v) => setDraft((prev) => ({ ...prev, trigger_type: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TRIGGERS.map((trigger) => <SelectItem key={trigger} value={trigger}>{trigger}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              {actions.map((action, index) => (
                <div key={`${action.id}-${index}`} className="grid gap-2 rounded-md border p-3 md:grid-cols-[180px_1fr_auto]">
                  <Select
                    value={String(action.type)}
                    onValueChange={(v) => {
                      const next = [...actions];
                      next[index] = { ...next[index], type: v };
                      setActions(next);
                    }}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {ACTIONS.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Textarea
                    className="font-mono text-xs"
                    rows={3}
                    value={JSON.stringify(action.config ?? {}, null, 2)}
                    onChange={(e) => {
                      try {
                        const next = [...actions];
                        next[index] = { ...next[index], config: JSON.parse(e.target.value) };
                        setActions(next);
                      } catch {
                        // Allow draft invalid JSON while typing.
                      }
                    }}
                  />
                  <Button variant="ghost" size="icon" onClick={() => setActions(actions.filter((_, i) => i !== index))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button variant="outline" onClick={() => setActions([...actions, { type: "message", config: { text: "" } }])}>
                <Plus className="mr-2 h-4 w-4" /> Agregar accion
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="visual" className="mt-4 h-[520px] rounded-md border">
            <ReactFlow
              nodes={(draft.definition.nodes ?? []).map((node, index) => ({
                id: String(node.id),
                position: { x: 120 + index * 220, y: index % 2 ? 180 : 80 },
                data: { label: `${node.type}` },
              }))}
              edges={(draft.definition.edges ?? []).map((edge, index) => ({
                id: `e-${index}`,
                source: String(edge.from),
                target: String(edge.to),
              }))}
              fitView
            >
              <Background />
              <Controls />
            </ReactFlow>
          </TabsContent>
          <TabsContent value="json" className="mt-4">
            <Textarea
              className="font-mono text-xs"
              rows={18}
              value={JSON.stringify(draft.definition, null, 2)}
              onChange={(e) => {
                try {
                  setDraft((prev) => ({ ...prev, definition: JSON.parse(e.target.value) }));
                } catch {
                  // Keep editing.
                }
              }}
            />
          </TabsContent>
          <TabsContent value="runs" className="mt-4 space-y-2">
            {executions.data?.map((run) => (
              <div key={run.id} className="rounded-md border p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span>{new Date(run.started_at).toLocaleString()}</span>
                  <Badge>{run.status}</Badge>
                </div>
                {run.error && <div className="mt-1 text-xs text-destructive">{run.error}</div>}
              </div>
            ))}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

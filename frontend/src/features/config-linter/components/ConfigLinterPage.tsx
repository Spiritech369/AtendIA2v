import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardCheck,
  GitBranch,
  Loader2,
  Network,
} from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { agentsApi, type ValidationIssue, type ValidationResult } from "@/features/agents/api";
import { tenantsApi, type ConfigValidationIssue } from "@/features/config/api";
import { workflowsApi, type WorkflowItem } from "@/features/workflows/api";
import { cn } from "@/lib/utils";

type LinterIssue = {
  code: string;
  severity: string;
  message: string;
  path?: string | null;
  source: "Agente IA" | "Pipeline" | "Workflow";
  sourceLabel: string;
};

function isBlockedSeverity(severity: string): boolean {
  return severity === "critical" || severity === "error";
}

function statusTone(status: string): string {
  if (status === "ready" || status === "ok") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700";
  if (status === "warning") return "border-amber-500/30 bg-amber-500/10 text-amber-700";
  return "border-red-500/30 bg-red-500/10 text-red-700";
}

function issueAction(issue: Pick<LinterIssue, "code" | "path">): { label: string; to: string; detail: string } {
  const code = issue.code;
  const path = issue.path ?? "";
  if (code.includes("CATALOG") || code.includes("QUOTE")) {
    return { label: "Ir a Catálogo", to: "/catalog", detail: "Carga productos oficiales con precio o planes." };
  }
  if (code.includes("MODE_WITHOUT_GUIDANCE") || path.includes("mode_prompts")) {
    return { label: "Ir a Composer", to: "/composer", detail: "Completa la guía del modo usado." };
  }
  if (code.includes("WORKFLOW")) {
    return { label: "Ir a Workflows", to: "/workflows", detail: "Corrige loops, nodos sin salida o publicación." };
  }
  if (code.includes("REQUIRED_FIELD")) {
    return { label: "Ir a Datos cliente", to: "/customer-fields", detail: "Crea o corrige el campo requerido." };
  }
  if (code.includes("DOCUMENT") && !path.includes("documents_catalog")) {
    return { label: "Ir a Conocimiento", to: "/knowledge", detail: "Sube o revisa documentos KB requeridos." };
  }
  if (path.includes("vision_doc_mapping") || path.includes("docs_per_plan") || path.includes("documents_catalog")) {
    return { label: "Ir a Expediente", to: "/expediente", detail: "Configura documentos, planes o auto-marcado Vision." };
  }
  return { label: "Ir a Configuración", to: "/config", detail: "Revisa la configuración relacionada." };
}

function agentIssues(agentName: string, validation: ValidationResult | undefined): LinterIssue[] {
  return (validation?.issues ?? []).map((issue: ValidationIssue) => ({
    code: issue.code,
    severity: issue.severity,
    message: issue.message,
    path: issue.path ?? issue.area ?? null,
    source: "Agente IA",
    sourceLabel: agentName,
  }));
}

function pipelineIssues(validation: { issues?: ConfigValidationIssue[] } | undefined): LinterIssue[] {
  return (validation?.issues ?? []).map((issue) => ({
    code: issue.code,
    severity: issue.severity,
    message: issue.message,
    path: issue.path ?? null,
    source: "Pipeline",
    sourceLabel: "Pipeline activo",
  }));
}

function workflowIssues(workflows: WorkflowItem[] | undefined): LinterIssue[] {
  return (workflows ?? []).flatMap((workflow) =>
    (workflow.validation?.issues ?? []).map((issue) => ({
      code: issue.code,
      severity: issue.severity,
      message: issue.message,
      path: issue.node_id ? `nodes.${issue.node_id}` : issue.area,
      source: "Workflow" as const,
      sourceLabel: workflow.name,
    })),
  );
}

export function ConfigLinterPage() {
  const agentsQuery = useQuery({ queryKey: ["agents", "config-linter"], queryFn: agentsApi.list });
  const pipelineQuery = useQuery({ queryKey: ["tenants", "pipeline", "config-linter"], queryFn: tenantsApi.getPipeline });
  const pipelineValidation = useQuery({
    queryKey: ["tenants", "pipeline", "config-linter", "validate", pipelineQuery.data?.version],
    queryFn: () => tenantsApi.validatePipeline(pipelineQuery.data?.definition ?? {}),
    enabled: !!pipelineQuery.data?.definition,
  });
  const workflowsQuery = useQuery({ queryKey: ["workflows", "config-linter"], queryFn: workflowsApi.list });
  const agentValidationQueries = useQueries({
    queries: (agentsQuery.data ?? []).map((agent) => ({
      queryKey: ["agents", agent.id, "config-linter", "validate"],
      queryFn: () => agentsApi.validateConfig(agent.id),
    })),
  });

  const agentValidations = agentValidationQueries.map((query, index) => ({
    agent: agentsQuery.data?.[index],
    validation: query.data,
    loading: query.isLoading,
  }));
  const issues = [
    ...agentValidations.flatMap((item) => item.agent ? agentIssues(item.agent.name, item.validation) : []),
    ...pipelineIssues(pipelineValidation.data),
    ...workflowIssues(workflowsQuery.data),
  ];
  const blockers = issues.filter((issue) => isBlockedSeverity(issue.severity));
  const warnings = issues.filter((issue) => issue.severity === "warning");
  const loading =
    agentsQuery.isLoading ||
    pipelineQuery.isLoading ||
    pipelineValidation.isLoading ||
    workflowsQuery.isLoading ||
    agentValidations.some((item) => item.loading);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Linter de configuración</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Bloqueos y advertencias antes de activar agentes, pipeline, workflows y cotizaciones.
          </p>
        </div>
        <div className="flex gap-2">
          <Badge variant={blockers.length ? "destructive" : "default"}>{blockers.length} críticos</Badge>
          <Badge variant="outline">{warnings.length} advertencias</Badge>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <StatusCard title="Agentes IA" icon={<Bot className="h-4 w-4" />} loading={agentsQuery.isLoading} statusText={`${agentValidations.length} revisado(s)`} blocked={agentValidations.flatMap((item) => agentIssues(item.agent?.name ?? "Agente", item.validation)).filter((i) => isBlockedSeverity(i.severity)).length} />
        <StatusCard title="Pipeline" icon={<GitBranch className="h-4 w-4" />} loading={pipelineValidation.isLoading} statusText={pipelineValidation.data?.summary ?? "Sin validar"} blocked={pipelineIssues(pipelineValidation.data).filter((i) => isBlockedSeverity(i.severity)).length} />
        <StatusCard title="Workflows" icon={<Network className="h-4 w-4" />} loading={workflowsQuery.isLoading} statusText={`${workflowsQuery.data?.length ?? 0} workflow(s)`} blocked={workflowIssues(workflowsQuery.data).filter((i) => isBlockedSeverity(i.severity)).length} />
      </div>

      <section className="rounded-md border bg-card">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <ClipboardCheck className="h-4 w-4" />
          <div className="font-medium">Bloqueos críticos del linter</div>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Revisando configuración...
          </div>
        ) : blockers.length === 0 ? (
          <div className="grid place-items-center p-8 text-center text-sm text-muted-foreground">
            <CheckCircle2 className="mb-2 h-8 w-8 text-emerald-500" />
            Sin bloqueos críticos. Puedes seguir con pruebas controladas.
          </div>
        ) : (
          <div className="divide-y">
            {blockers.map((issue) => (
              <IssueRow key={`${issue.source}-${issue.sourceLabel}-${issue.code}-${issue.path ?? issue.message}`} issue={issue} />
            ))}
          </div>
        )}
      </section>

      {warnings.length > 0 && (
        <section className="rounded-md border bg-card">
          <div className="flex items-center gap-2 border-b px-4 py-3">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <div className="font-medium">Advertencias</div>
          </div>
          <div className="divide-y">
            {warnings.map((issue) => (
              <IssueRow key={`${issue.source}-${issue.sourceLabel}-${issue.code}-${issue.path ?? issue.message}`} issue={issue} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function StatusCard({
  title,
  icon,
  loading,
  statusText,
  blocked,
}: {
  title: string;
  icon: ReactNode;
  loading: boolean;
  statusText: string;
  blocked: number;
}) {
  return (
    <div className={cn("rounded-md border p-3", statusTone(blocked ? "blocked" : "ready"))}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium">
          {icon}
          {title}
        </div>
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Badge variant={blocked ? "destructive" : "outline"}>{blocked ? `${blocked} bloquea` : "OK"}</Badge>}
      </div>
      <div className="mt-2 text-xs opacity-80">{statusText}</div>
    </div>
  );
}

function IssueRow({ issue }: { issue: LinterIssue }) {
  const action = issueAction(issue);
  return (
    <div className="grid gap-3 p-4 md:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={isBlockedSeverity(issue.severity) ? "destructive" : "outline"}>{issue.severity}</Badge>
          <span className="text-sm font-medium">{issue.source}</span>
          <span className="text-sm text-muted-foreground">{issue.sourceLabel}</span>
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{issue.code}</code>
        </div>
        <p className="mt-2 text-sm">{issue.message}</p>
        {issue.path && <p className="mt-1 font-mono text-xs text-muted-foreground">{issue.path}</p>}
        <p className="mt-2 text-xs text-muted-foreground">{action.detail}</p>
      </div>
      <div className="flex items-center">
        <Button asChild size="sm">
          <Link to={action.to}>{action.label}</Link>
        </Button>
      </div>
    </div>
  );
}

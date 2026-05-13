import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowUp,
  Bell,
  Bot,
  Brain,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Download,
  Eye,
  FileText,
  Filter,
  MessageCircle,
  MoreHorizontal,
  Phone,
  Plus,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  UserCog,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  type ClientStage,
  type CustomerDetail,
  type CustomerListItem,
  type NextBestAction,
  customersApi,
} from "@/features/customers/api";
import { cn } from "@/lib/utils";
import { ImportCustomersDialog } from "./ImportCustomersDialog";

const STAGES: { value: ClientStage; label: string }[] = [
  { value: "new", label: "Nuevo" },
  { value: "in_conversation", label: "En conversación" },
  { value: "qualified", label: "Calificado" },
  { value: "negotiation", label: "Negociación" },
  { value: "documentation", label: "Documentación" },
  { value: "pending_handoff", label: "Handoff pendiente" },
  { value: "closed_won", label: "Ganado" },
  { value: "closed_lost", label: "Perdido" },
  { value: "lost_risk", label: "Lost risk" },
];

const ACTION_LABELS: Record<string, string> = {
  send_follow_up: "Enviar seguimiento",
  request_documents: "Solicitar docs",
  assign_seller: "Asignar vendedor",
  call_now: "Llamar ahora",
  review_conversation: "Revisar conversación",
  escalate_to_human: "Escalar a humano",
  move_to_negotiation: "Mover a negociación",
  mark_lost_risk: "Marcar riesgo",
  reassign: "Reasignar",
  schedule_appointment: "Agendar cita",
};

function stageLabel(stage: string | null | undefined) {
  return STAGES.find((s) => s.value === stage)?.label ?? stage ?? "Sin etapa";
}

function rel(iso: string | null) {
  if (!iso) return "-";
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.max(0, Math.round(diff / 60_000));
  if (min < 1) return "ahora";
  if (min < 60) return `${min}m`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

function initials(name: string | null, phone: string) {
  const source = name?.trim() || phone;
  const parts = source.split(/\s+/);
  if (parts.length > 1) return `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function riskClass(level: string) {
  if (level === "critical") return "border-red-300 bg-red-50 text-red-700";
  if (level === "high") return "border-rose-300 bg-rose-50 text-rose-700";
  if (level === "medium") return "border-amber-300 bg-amber-50 text-amber-700";
  return "border-emerald-300 bg-emerald-50 text-emerald-700";
}

function slaClass(status: string) {
  if (status === "breached") return "border-red-300 bg-red-50 text-red-700";
  if (status === "attention_soon") return "border-amber-300 bg-amber-50 text-amber-700";
  return "border-emerald-300 bg-emerald-50 text-emerald-700";
}

function stageClass(stage: string | null | undefined) {
  if (stage === "negotiation") return "border-orange-300 bg-orange-50 text-orange-700";
  if (stage === "documentation") return "border-blue-300 bg-blue-50 text-blue-700";
  if (stage === "qualified") return "border-emerald-300 bg-emerald-50 text-emerald-700";
  if (stage === "lost_risk" || stage === "closed_lost") return "border-red-300 bg-red-50 text-red-700";
  if (stage === "closed_won") return "border-teal-300 bg-teal-50 text-teal-700";
  return "border-slate-300 bg-slate-50 text-slate-700";
}

function ScoreBar({ value }: { value: number }) {
  const color = value >= 75 ? "bg-emerald-500" : value >= 55 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <span className="w-6 text-right text-xs font-medium tabular-nums">{value}</span>
      <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-200">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.max(4, value)}%` }} />
      </div>
    </div>
  );
}

function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium", className)}>
      {children}
    </span>
  );
}

function KpiCard({
  title,
  value,
  delta,
  icon: Icon,
  tone = "blue",
}: {
  title: string;
  value: number | string;
  delta?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "blue" | "red" | "amber" | "emerald" | "violet";
}) {
  const toneClass = {
    blue: "text-blue-600 bg-blue-50 border-blue-100",
    red: "text-red-600 bg-red-50 border-red-100",
    amber: "text-amber-600 bg-amber-50 border-amber-100",
    emerald: "text-emerald-600 bg-emerald-50 border-emerald-100",
    violet: "text-violet-600 bg-violet-50 border-violet-100",
  }[tone];
  return (
    <button className="min-h-24 rounded-lg border bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="text-xs font-medium text-slate-600">{title}</div>
        <div className={cn("rounded-lg border p-1.5", toneClass)}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">{value}</div>
      {delta && (
        <div className="mt-1 flex items-center gap-1 text-xs text-red-600">
          <ArrowUp className="h-3 w-3" />
          {delta}
        </div>
      )}
    </button>
  );
}

function CustomerTableRow({
  customer,
  selected,
  onSelect,
}: {
  customer: CustomerListItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <tr
      className={cn(
        "border-b border-slate-100 text-sm transition-colors hover:bg-blue-50/40",
        selected && "bg-blue-50",
      )}
    >
      <td className="w-10 px-3 py-3">
        <input type="checkbox" className="h-4 w-4 rounded border-slate-300 accent-blue-600" aria-label="Seleccionar cliente" />
      </td>
      <td className="min-w-56 px-3 py-3">
        <button type="button" onClick={onSelect} className="flex min-w-0 items-center gap-3 text-left">
          <Avatar className="h-8 w-8 border">
            <AvatarFallback className="bg-slate-100 text-xs font-semibold text-slate-700">
              {initials(customer.name, customer.phone_e164)}
            </AvatarFallback>
          </Avatar>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="truncate font-semibold text-slate-900">{customer.name ?? "Sin nombre"}</span>
              {customer.health_score >= 85 && <Sparkles className="h-3.5 w-3.5 text-amber-500" />}
            </span>
            <span className="block truncate text-xs text-slate-500">{customer.source ?? "WhatsApp"}</span>
          </span>
        </button>
      </td>
      <td className="px-3 py-3 font-mono text-xs text-slate-600">{customer.phone_e164}</td>
      <td className="px-3 py-3">
        <Pill className={stageClass(customer.stage)}>{stageLabel(customer.stage)}</Pill>
      </td>
      <td className="px-3 py-3">
        <ScoreBar value={customer.health_score || customer.score} />
      </td>
      <td className="px-3 py-3">
        <Pill className={riskClass(customer.risk_level)}>{customer.risk_level}</Pill>
      </td>
      <td className="px-3 py-3">
        <Pill className={slaClass(customer.sla_status)}>
          {customer.sla_status === "attention_soon" ? "At risk" : customer.sla_status === "breached" ? "Breached" : "On track"}
        </Pill>
      </td>
      <td className="px-3 py-3 text-xs font-medium text-red-600">{rel(customer.last_activity_at)}</td>
      <td className="px-3 py-3">
        {customer.assigned_user_email ? (
          <div className="flex items-center gap-2 text-xs text-slate-700">
            <Avatar className="h-6 w-6">
              <AvatarFallback className="text-[10px]">{customer.assigned_user_email.slice(0, 2).toUpperCase()}</AvatarFallback>
            </Avatar>
            {customer.assigned_user_email.split("@")[0]}
          </div>
        ) : (
          <span className="text-xs text-slate-400">-</span>
        )}
      </td>
      <td className="min-w-44 px-3 py-3">
        <Button variant="outline" size="sm" className="h-7 border-blue-200 text-xs text-blue-700">
          <Send className="mr-1.5 h-3 w-3" />
          {ACTION_LABELS[customer.next_best_action ?? ""] ?? "Revisar"}
        </Button>
      </td>
      <td className="min-w-64 px-3 py-3 text-xs text-slate-600">{customer.ai_insight_reason ?? customer.ai_summary ?? "-"}</td>
      <td className="w-12 px-3 py-3 text-right">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild>
              <Link to="/customers/$customerId" params={{ customerId: customer.id }}>
                Ver ficha completa
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onSelect}>Abrir panel</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </td>
    </tr>
  );
}

function IntelligencePanel({
  customerId,
  onClose,
}: {
  customerId: string | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["customer", "detail-panel", customerId],
    queryFn: () => customersApi.getOne(customerId!),
    enabled: Boolean(customerId),
  });
  const execute = useMutation({
    mutationFn: ({ customerId, actionId }: { customerId: string; actionId: string }) =>
      customersApi.executeAction(customerId, actionId),
    onSuccess: () => {
      toast.success("Acción registrada");
      void qc.invalidateQueries({ queryKey: ["customers"] });
      void qc.invalidateQueries({ queryKey: ["customer", "detail-panel", customerId] });
    },
    onError: (e: Error) => toast.error("No se pudo ejecutar", { description: e.message }),
  });
  const message = useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) =>
      customersApi.createMessage(id, { body, sender_type: "human" }),
    onSuccess: () => {
      toast.success("Mensaje simulado registrado");
      void qc.invalidateQueries({ queryKey: ["customer", "detail-panel", customerId] });
    },
  });

  const customer = detail.data;
  const objections = Array.isArray(customer?.attrs?.objections) ? (customer?.attrs.objections as string[]) : [];
  const received = customer?.documents.filter((d) => d.status === "received" || d.status === "approved") ?? [];
  const missing = customer?.documents.filter((d) => d.status === "missing" || d.status === "rejected") ?? [];
  const topAction = customer?.next_best_actions[0];

  return (
    <aside className="flex h-full w-[360px] shrink-0 flex-col border-l bg-white">
      <div className="flex h-14 items-center justify-between border-b px-5">
        <div className="text-sm font-semibold text-slate-900">Client Intelligence Panel</div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {!customerId ? (
        <div className="grid flex-1 place-items-center p-8 text-center text-sm text-slate-500">
          Selecciona un cliente para ver contexto, riesgos y siguiente acción.
        </div>
      ) : detail.isLoading ? (
        <div className="space-y-4 p-5">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : customer ? (
        <div className="flex-1 overflow-auto p-5">
          <div className="flex items-start gap-3">
            <Avatar className="h-12 w-12 border">
              <AvatarFallback className="font-semibold">{initials(customer.name, customer.phone_e164)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <h2 className="truncate text-base font-semibold text-slate-950">{customer.name ?? "Sin nombre"}</h2>
                {customer.health_score >= 85 && <Sparkles className="h-4 w-4 text-amber-500" />}
              </div>
              <div className="text-xs text-slate-500">{customer.phone_e164}</div>
              <div className="mt-2 flex gap-2">
                <Pill className={stageClass(customer.stage)}>{stageLabel(customer.stage)}</Pill>
                <Pill className={riskClass(customer.risk_level)}>{customer.risk_level}</Pill>
              </div>
            </div>
          </div>

          <section className="mt-5 rounded-lg border bg-violet-50/60 p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-violet-800">
              <Brain className="h-4 w-4" />
              AI summary
            </div>
            <p className="text-sm leading-relaxed text-slate-700">
              {customer.ai_summary ?? customer.ai_insight_reason ?? "Sin resumen IA todavía."}
            </p>
          </section>

          <section className="mt-4 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-slate-800">Última conversación</h3>
              <span className="text-xs text-slate-500">{rel(customer.last_activity_at)}</span>
            </div>
            <div className="mt-3 space-y-2">
              {customer.messages.slice(0, 3).map((m) => (
                <div key={m.id} className="rounded-md bg-slate-50 p-2 text-xs text-slate-700">
                  <span className="font-semibold">{m.sender_type}: </span>
                  {m.body}
                </div>
              ))}
              {customer.messages.length === 0 && <div className="text-xs text-slate-500">Sin mensajes registrados.</div>}
            </div>
            {customer.conversations[0] && (
              <Button variant="link" className="mt-2 h-auto p-0 text-xs" asChild>
                <Link to="/conversations/$conversationId" params={{ conversationId: customer.conversations[0].id }}>
                  Abrir conversación
                </Link>
              </Button>
            )}
          </section>

          <section className="mt-4">
            <h3 className="text-xs font-semibold text-slate-800">Objeciones detectadas</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {objections.length ? objections.map((o) => <Pill key={o} className="border-red-200 bg-red-50 text-red-700">{o}</Pill>) : (
                <span className="text-xs text-slate-500">Sin objeciones activas.</span>
              )}
            </div>
          </section>

          <section className="mt-4 rounded-lg border p-4">
            <div className="flex items-center justify-between text-xs">
              <h3 className="font-semibold text-slate-800">Documentos</h3>
              <span className="text-slate-500">{received.length}/{customer.documents.length} recibidos</span>
            </div>
            <div className="mt-3 grid gap-1.5">
              {customer.documents.slice(0, 5).map((doc) => (
                <div key={doc.id} className="flex items-center justify-between text-xs">
                  <span className="truncate text-slate-600">{doc.label}</span>
                  <span className={cn("font-medium", doc.status === "missing" ? "text-red-600" : "text-emerald-600")}>
                    {doc.status}
                  </span>
                </div>
              ))}
            </div>
            {missing.length > 0 && <div className="mt-2 text-xs text-amber-700">Faltan: {missing.slice(0, 2).map((d) => d.label).join(", ")}</div>}
          </section>

          <section className="mt-4 grid grid-cols-2 gap-3">
            <div className="rounded-lg border p-3">
              <div className="text-xs text-slate-500">Última acción IA</div>
              <div className="mt-1 text-sm font-medium text-slate-800">{customer.ai_confidence ? `${Math.round(customer.ai_confidence * 100)}% confianza` : "-"}</div>
            </div>
            <div className="rounded-lg border p-3">
              <div className="text-xs text-slate-500">Última acción humana</div>
              <div className="mt-1 text-sm font-medium text-slate-800">{customer.assigned_user_email?.split("@")[0] ?? "Sin dueño"}</div>
            </div>
          </section>

          <section className="mt-4">
            <h3 className="text-xs font-semibold text-slate-800">Timeline</h3>
            <div className="mt-3 space-y-3">
              {customer.timeline.slice(0, 5).map((event) => (
                <div key={event.id} className="flex gap-2 text-xs">
                  <span className="mt-1 h-2 w-2 rounded-full bg-blue-500" />
                  <div>
                    <div className="font-medium text-slate-800">{event.title}</div>
                    <div className="text-slate-500">{rel(event.created_at)} · {event.actor_type}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-5 rounded-lg border bg-slate-50 p-4">
            <h3 className="text-xs font-semibold text-slate-800">Recommended next step</h3>
            {topAction ? (
              <>
                <p className="mt-2 text-xs text-slate-600">{topAction.reason}</p>
                <Button
                  className="mt-3 w-full"
                  size="sm"
                  disabled={execute.isPending}
                  onClick={() => execute.mutate({ customerId: customer.id, actionId: topAction.id })}
                >
                  <Send className="mr-2 h-3.5 w-3.5" />
                  {ACTION_LABELS[topAction.action_type] ?? topAction.action_type}
                </Button>
              </>
            ) : (
              <p className="mt-2 text-xs text-slate-500">Sin recomendación activa.</p>
            )}
          </section>

          <div className="mt-4 grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm" onClick={() => message.mutate({ id: customer.id, body: "Seguimiento manual desde AtendIA." })}>
              <MessageCircle className="mr-1.5 h-3.5 w-3.5" />
              Send message
            </Button>
            <Button variant="outline" size="sm">
              <UserCog className="mr-1.5 h-3.5 w-3.5" />
              Reassign
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link to="/customers/$customerId" params={{ customerId: customer.id }}>
                <Eye className="mr-1.5 h-3.5 w-3.5" />
                Full profile
              </Link>
            </Button>
            <Button variant="outline" size="sm" onClick={() => toast.info("Audit trail disponible en ficha completa")}>
              <FileText className="mr-1.5 h-3.5 w-3.5" />
              Audit trail
            </Button>
          </div>
        </div>
      ) : (
        <div className="p-5 text-sm text-red-600">No se pudo cargar el cliente.</div>
      )}
    </aside>
  );
}

function NewClientDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [stage, setStage] = useState<ClientStage>("new");
  const create = useMutation({
    mutationFn: () => customersApi.create({ name: name || null, phone_e164: phone, stage, tags: ["manual"], source: "Manual" }),
    onSuccess: () => {
      toast.success("Cliente creado");
      setOpen(false);
      setName("");
      setPhone("");
      void qc.invalidateQueries({ queryKey: ["customers"] });
    },
    onError: (e: Error) => toast.error("No se pudo crear", { description: e.message }),
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="h-9 gap-2">
          <Plus className="h-4 w-4" />
          New client
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo cliente</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <Input placeholder="Nombre" value={name} onChange={(e) => setName(e.target.value)} />
          <Input placeholder="+52..." value={phone} onChange={(e) => setPhone(e.target.value)} />
          <Select value={stage} onValueChange={(v) => setStage(v as ClientStage)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STAGES.map((s) => (
                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancelar</Button>
          <Button disabled={!phone || create.isPending} onClick={() => create.mutate()}>Crear</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ClientsPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("all");
  const [filter, setFilter] = useState<"all" | "high_score" | "idle" | "unassigned" | "negotiation" | "docs" | "sla">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdQ, setCmdQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCmdOpen(true);
      }
      if (event.key === "/" && document.activeElement?.tagName !== "INPUT") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const list = useQuery({
    queryKey: ["customers", "command-center", q, stage, filter],
    queryFn: () =>
      customersApi.list({
        q: q || undefined,
        stage: stage === "all" ? undefined : stage,
        risk_level: filter === "idle" ? "high" : undefined,
        sla_status: filter === "sla" ? "breached" : undefined,
        sort_by: "last_activity",
        sort_dir: "desc",
        limit: 100,
      }),
    staleTime: 20_000,
  });
  const kpis = useQuery({
    queryKey: ["customers", "kpis"],
    queryFn: customersApi.kpis,
    staleTime: 20_000,
  });
  const radar = useQuery({
    queryKey: ["customers", "risk-radar"],
    queryFn: customersApi.riskRadar,
    staleTime: 20_000,
  });
  const aiQueue = useQuery({
    queryKey: ["customers", "ai-review"],
    queryFn: customersApi.aiReviewQueue,
    staleTime: 30_000,
  });

  const items = useMemo(() => {
    const base = list.data?.items ?? [];
    if (filter === "high_score") return base.filter((c) => c.health_score >= 80 && rel(c.last_activity_at).endsWith("h"));
    if (filter === "unassigned") return base.filter((c) => !c.assigned_user_id);
    if (filter === "negotiation") return base.filter((c) => c.stage === "negotiation");
    if (filter === "docs") return base.filter((c) => c.documents_status !== "complete");
    return base;
  }, [list.data?.items, filter]);

  useEffect(() => {
    if (!selectedId && items[0]) setSelectedId(items[0].id);
  }, [items, selectedId]);

  const cmdItems = useMemo(() => {
    const term = cmdQ.toLowerCase().trim();
    return (list.data?.items ?? [])
      .filter((c) => !term || (c.name ?? "").toLowerCase().includes(term) || c.phone_e164.includes(term))
      .slice(0, 8);
  }, [cmdQ, list.data?.items]);

  const refreshAll = () => {
    void qc.invalidateQueries({ queryKey: ["customers"] });
  };

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] overflow-hidden bg-slate-50 text-slate-950">
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-16 shrink-0 items-center gap-4 border-b bg-white px-6">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold tracking-tight">Clients</h1>
            <p className="text-xs text-slate-500">Operational overview of client health, risk, and next best actions.</p>
          </div>
          <div className="relative ml-6 max-w-xl flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              ref={searchRef}
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="Search clients, conversations, or insights..."
              className="h-9 rounded-lg border-slate-200 bg-white pl-9 pr-14"
            />
            <button type="button" onClick={() => setCmdOpen(true)} className="absolute right-2 top-1.5 rounded border bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
              Ctrl K
            </button>
          </div>
          <Button variant="outline" size="sm" className="h-9 gap-2" asChild>
            <a href={customersApi.exportCsvUrl()}>
              <Download className="h-4 w-4" />
              Export
            </a>
          </Button>
          <ImportCustomersDialog />
          <NewClientDialog />
        </header>

        <div className="flex-1 overflow-auto p-6">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[repeat(6,minmax(0,1fr))]">
            <KpiCard title="Clients needing attention" value={kpis.data?.clients_needing_attention ?? 0} delta="+20%" icon={ShieldAlert} tone="red" />
            <KpiCard title="High-score w/o follow-up" value={kpis.data?.high_score_without_followup ?? 0} delta="+17%" icon={Zap} tone="amber" />
            <KpiCard title="At-risk clients" value={kpis.data?.at_risk_clients ?? 0} delta="+25%" icon={AlertTriangle} tone="red" />
            <KpiCard title="Unassigned clients" value={kpis.data?.unassigned_clients ?? 0} delta="+15%" icon={Users} tone="violet" />
            <KpiCard title="Documentation pending" value={kpis.data?.documentation_pending ?? 0} delta="+12%" icon={FileText} tone="blue" />
            <KpiCard title="Active negotiations" value={kpis.data?.active_negotiations ?? 0} delta="+8%" icon={CheckCircle2} tone="emerald" />
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[1fr_280px]">
            <div className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative min-w-72 flex-1">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                  <Input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search clients..." className="h-9 pl-9" />
                </div>
                <Select value={stage} onValueChange={setStage}>
                  <SelectTrigger className="h-9 w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All stages</SelectItem>
                    {STAGES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button variant="outline" size="sm" className="h-9 gap-2">
                  <Columns3 className="h-4 w-4" />
                  Columns
                </Button>
                <Button variant="outline" size="sm" className="h-9 gap-2" onClick={refreshAll}>
                  <Filter className="h-4 w-4" />
                  Refresh
                </Button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {[
                  ["all", "All stages"],
                  ["high_score", "High score"],
                  ["idle", "No activity > 8h"],
                  ["unassigned", "Unassigned"],
                  ["negotiation", "Negotiation"],
                  ["docs", "Documentation incomplete"],
                  ["sla", "SLA breached"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setFilter(value as typeof filter)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium",
                      filter === value ? "border-blue-300 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <section className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-900">Operational Risk Radar</h2>
                <span className="text-[11px] text-slate-500">Updated now</span>
              </div>
              <div className="mt-3 space-y-2">
                {(radar.data?.items ?? []).slice(0, 5).map((item) => (
                  <button key={item.title} className="flex w-full items-center justify-between rounded-md px-1.5 py-1.5 text-left hover:bg-slate-50">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className={cn("h-2.5 w-2.5 rounded-full", item.severity === "critical" || item.severity === "high" ? "bg-red-500" : item.severity === "medium" ? "bg-amber-500" : "bg-emerald-500")} />
                      <span className="truncate text-xs text-slate-700">{item.title}</span>
                    </span>
                    <span className="text-xs font-semibold text-slate-900">{item.count}</span>
                  </button>
                ))}
                {radar.isLoading && <Skeleton className="h-20 w-full" />}
                {!radar.isLoading && (radar.data?.items.length ?? 0) === 0 && <div className="text-xs text-slate-500">Sin alertas activas.</div>}
              </div>
            </section>
          </div>

          <section className="mt-5 overflow-hidden rounded-lg border bg-white shadow-sm">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div className="text-sm font-semibold text-slate-900">Clients Command Center</div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <Bell className="h-3.5 w-3.5 text-red-500" />
                AI review queue: {aiQueue.data?.items.length ?? 0}
              </div>
            </div>
            <div className="overflow-auto">
              <table className="w-full border-collapse">
                <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="w-10 px-3 py-2.5"><input type="checkbox" className="h-4 w-4 rounded border-slate-300 accent-blue-600" /></th>
                    <th className="px-3 py-2.5">Client</th>
                    <th className="px-3 py-2.5">Phone</th>
                    <th className="px-3 py-2.5">Stage</th>
                    <th className="px-3 py-2.5">Health score</th>
                    <th className="px-3 py-2.5">Risk level</th>
                    <th className="px-3 py-2.5">SLA status</th>
                    <th className="px-3 py-2.5">Last activity</th>
                    <th className="px-3 py-2.5">Assigned to</th>
                    <th className="px-3 py-2.5">Next best action</th>
                    <th className="px-3 py-2.5">AI insight / reason</th>
                    <th className="w-12 px-3 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {list.isLoading ? (
                    Array.from({ length: 8 }).map((_, index) => (
                      <tr key={index} className="border-b">
                        <td colSpan={12} className="px-4 py-3"><Skeleton className="h-9 w-full" /></td>
                      </tr>
                    ))
                  ) : items.length ? (
                    items.map((customer) => (
                      <CustomerTableRow
                        key={customer.id}
                        customer={customer}
                        selected={customer.id === selectedId}
                        onSelect={() => setSelectedId(customer.id)}
                      />
                    ))
                  ) : (
                    <tr>
                      <td colSpan={12} className="px-4 py-16 text-center text-sm text-slate-500">
                        Sin clientes para estos filtros.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <footer className="flex items-center justify-between border-t px-4 py-3 text-xs text-slate-500">
              <span>Showing 1-{items.length} of {kpis.data?.total_clients ?? items.length} clients</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="icon" className="h-7 w-7" disabled><ChevronLeft className="h-3.5 w-3.5" /></Button>
                <Button size="sm" className="h-7 w-7 p-0">1</Button>
                <Button variant="ghost" size="sm" className="h-7 w-7 p-0">2</Button>
                <Button variant="outline" size="icon" className="h-7 w-7"><ChevronRight className="h-3.5 w-3.5" /></Button>
              </div>
            </footer>
          </section>
        </div>
      </main>

      <IntelligencePanel customerId={selectedId} onClose={() => setSelectedId(null)} />

      <CommandDialog open={cmdOpen} onOpenChange={setCmdOpen} title="Buscar clientes" description="Busca por nombre o teléfono">
        <CommandInput value={cmdQ} onValueChange={setCmdQ} placeholder="Cliente, teléfono o insight..." />
        <CommandList>
          <CommandEmpty>Sin resultados</CommandEmpty>
          <CommandGroup heading="Clientes">
            {cmdItems.map((customer) => (
              <CommandItem
                key={customer.id}
                value={`${customer.name ?? ""} ${customer.phone_e164}`}
                onSelect={() => {
                  setSelectedId(customer.id);
                  setCmdOpen(false);
                }}
              >
                <Avatar className="mr-2 h-6 w-6"><AvatarFallback>{initials(customer.name, customer.phone_e164)}</AvatarFallback></Avatar>
                <span className="flex-1">{customer.name ?? customer.phone_e164}</span>
                <Badge variant="outline">{stageLabel(customer.stage)}</Badge>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </div>
  );
}

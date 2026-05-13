import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Brain,
  CheckCircle2,
  Clock,
  FileText,
  MessageCircle,
  Phone,
  Plus,
  Send,
  ShieldAlert,
  Sparkles,
  StickyNote,
  UserCog,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  type ClientStage,
  type CustomerDetail as CustomerDetailType,
  customersApi,
  notesApi,
} from "@/features/customers/api";
import { cn } from "@/lib/utils";

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
  request_documents: "Solicitar documentos",
  assign_seller: "Asignar vendedor",
  call_now: "Llamar ahora",
  review_conversation: "Revisar conversación",
  escalate_to_human: "Escalar a humano",
  move_to_negotiation: "Mover a negociación",
  schedule_appointment: "Agendar cita",
};

function initials(name: string | null, phone: string) {
  const source = name || phone;
  const parts = source.trim().split(/\s+/);
  if (parts.length > 1) return `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
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

function stageLabel(stage: string) {
  return STAGES.find((s) => s.value === stage)?.label ?? stage;
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

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function ScoreBreakdown({ customer }: { customer: CustomerDetailType }) {
  const score = customer.latest_score;
  const rows = score
    ? [
        ["Intent", score.intent_score],
        ["Activity", score.activity_score],
        ["Documents", score.documentation_score],
        ["Data quality", score.data_quality_score],
        ["Engagement", score.conversation_engagement_score],
        ["Stage progress", score.stage_progress_score],
      ]
    : [];
  return (
    <section className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Health score engine</h2>
        <Badge variant="outline">{customer.health_score}/100</Badge>
      </div>
      <p className="mt-2 text-sm text-slate-600">
        {String(score?.explanation?.summary ?? customer.ai_insight_reason ?? "Score pendiente de calcular.")}
      </p>
      <div className="mt-4 grid gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[120px_1fr_40px] items-center gap-3 text-xs">
            <span className="text-slate-500">{label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-blue-500" style={{ width: `${value}%` }} />
            </div>
            <span className="text-right font-medium tabular-nums">{value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function NewNoteDialog({ customerId, open, onOpenChange }: { customerId: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const qc = useQueryClient();
  const [content, setContent] = useState("");
  const create = useMutation({
    mutationFn: () => notesApi.create(customerId, { content, pinned: false }),
    onSuccess: () => {
      toast.success("Nota agregada");
      setContent("");
      onOpenChange(false);
      void qc.invalidateQueries({ queryKey: ["customer-notes", customerId] });
    },
    onError: (e: Error) => toast.error("No se pudo guardar", { description: e.message }),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nueva nota</DialogTitle>
        </DialogHeader>
        <Textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="Contexto comercial, objeción, acuerdo..." />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button disabled={!content.trim() || create.isPending} onClick={() => create.mutate()}>Guardar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CustomerDetail({ customerId }: { customerId: string }) {
  const qc = useQueryClient();
  const [noteOpen, setNoteOpen] = useState(false);
  const [messageText, setMessageText] = useState("");

  const detail = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => customersApi.getOne(customerId),
  });
  const notes = useQuery({
    queryKey: ["customer-notes", customerId],
    queryFn: () => notesApi.list(customerId),
  });

  const changeStage = useMutation({
    mutationFn: (stage: ClientStage) => customersApi.changeStage(customerId, stage),
    onSuccess: () => {
      toast.success("Etapa actualizada");
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    },
    onError: (e: Error) => toast.error("No se pudo cambiar etapa", { description: e.message }),
  });
  const execute = useMutation({
    mutationFn: (actionId: string) => customersApi.executeAction(customerId, actionId),
    onSuccess: () => {
      toast.success("Acción ejecutada");
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    },
    onError: (e: Error) => toast.error("No se pudo ejecutar", { description: e.message }),
  });
  const sendMessage = useMutation({
    mutationFn: () => customersApi.createMessage(customerId, { body: messageText, sender_type: "human" }),
    onSuccess: () => {
      toast.success("Mensaje simulado registrado");
      setMessageText("");
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    },
  });
  const patchDoc = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => customersApi.patchDocument(id, { status }),
    onSuccess: () => {
      toast.success("Documento actualizado");
      void qc.invalidateQueries({ queryKey: ["customer", customerId] });
    },
  });

  const customer = detail.data;
  const objections = useMemo(
    () => (Array.isArray(customer?.attrs?.objections) ? (customer?.attrs.objections as string[]) : []),
    [customer?.attrs],
  );
  const topAction = customer?.next_best_actions[0];
  const receivedDocs = customer?.documents.filter((d) => d.status === "received" || d.status === "approved").length ?? 0;

  if (detail.isLoading) {
    return (
      <div className="-m-6 space-y-4 bg-slate-50 p-6">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }

  if (!customer) {
    return (
      <div className="-m-6 grid min-h-[calc(100vh-3.5rem)] place-items-center bg-slate-50">
        <div className="text-sm text-slate-500">Cliente no encontrado.</div>
      </div>
    );
  }

  return (
    <div className="-m-6 min-h-[calc(100vh-3.5rem)] bg-slate-50 text-slate-950">
      <header className="sticky top-0 z-20 border-b bg-white/95 px-6 py-4 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" asChild>
              <Link to="/customers">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <Avatar className="h-12 w-12 border">
              <AvatarFallback className="font-semibold">{initials(customer.name, customer.phone_e164)}</AvatarFallback>
            </Avatar>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-semibold tracking-tight">{customer.name ?? "Sin nombre"}</h1>
                {customer.health_score >= 85 && <Sparkles className="h-4 w-4 text-amber-500" />}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{customer.phone_e164}</span>
                <span>·</span>
                <span>{customer.email ?? "sin email"}</span>
                <span>·</span>
                <span>Última actividad {rel(customer.last_activity_at)}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Select value={customer.stage as ClientStage} onValueChange={(v) => changeStage.mutate(v as ClientStage)}>
              <SelectTrigger className="h-9 w-48 bg-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STAGES.map((stage) => (
                  <SelectItem key={stage.value} value={stage.value}>{stage.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" className="h-9 gap-2">
              <UserCog className="h-4 w-4" />
              Reassign
            </Button>
            <Button className="h-9 gap-2" disabled={!topAction || execute.isPending} onClick={() => topAction && execute.mutate(topAction.id)}>
              <Send className="h-4 w-4" />
              {topAction ? ACTION_LABELS[topAction.action_type] ?? topAction.action_type : "No action"}
            </Button>
          </div>
        </div>
      </header>

      <main className="p-6">
        <div className="grid gap-4 md:grid-cols-4">
          <Stat label="Health score" value={`${customer.health_score}/100`} icon={Brain} />
          <Stat label="Risk level" value={customer.risk_level} icon={ShieldAlert} />
          <Stat label="SLA status" value={customer.sla_status === "attention_soon" ? "At risk" : customer.sla_status} icon={Clock} />
          <Stat label="Documents" value={`${receivedDocs}/${customer.documents.length}`} icon={FileText} />
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_340px]">
          <section className="min-w-0">
            <Tabs defaultValue="overview" className="space-y-4">
              <TabsList className="bg-white">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="timeline">Timeline</TabsTrigger>
                <TabsTrigger value="conversation">Conversation</TabsTrigger>
                <TabsTrigger value="documents">Documents</TabsTrigger>
                <TabsTrigger value="risks">Risks</TabsTrigger>
                <TabsTrigger value="audit">Audit</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="space-y-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <section className="rounded-lg border bg-white p-4 shadow-sm">
                    <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                      <Bot className="h-4 w-4 text-violet-600" />
                      AI supervision
                    </div>
                    <p className="text-sm leading-relaxed text-slate-700">{customer.ai_summary ?? customer.ai_insight_reason ?? "Sin resumen IA."}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge variant="outline" className={cn("capitalize", riskClass(customer.risk_level))}>{customer.risk_level}</Badge>
                      <Badge variant="outline" className={cn("capitalize", slaClass(customer.sla_status))}>{customer.sla_status}</Badge>
                      {customer.ai_confidence && <Badge variant="outline">{Math.round(customer.ai_confidence * 100)}% confianza IA</Badge>}
                    </div>
                  </section>
                  <section className="rounded-lg border bg-white p-4 shadow-sm">
                    <div className="mb-2 text-sm font-semibold">Next best actions</div>
                    <div className="space-y-2">
                      {customer.next_best_actions.map((action) => (
                        <button
                          key={action.id}
                          className="w-full rounded-md border p-3 text-left hover:bg-blue-50"
                          onClick={() => execute.mutate(action.id)}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-sm font-medium">{ACTION_LABELS[action.action_type] ?? action.action_type}</span>
                            <Badge variant="outline">{action.priority}</Badge>
                          </div>
                          <p className="mt-1 text-xs text-slate-600">{action.reason}</p>
                        </button>
                      ))}
                      {customer.next_best_actions.length === 0 && <div className="text-sm text-slate-500">Sin acciones activas.</div>}
                    </div>
                  </section>
                </div>
                <ScoreBreakdown customer={customer} />
                <section className="rounded-lg border bg-white p-4 shadow-sm">
                  <div className="text-sm font-semibold">Objections detected</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {objections.length ? objections.map((item) => <Badge key={item} variant="outline" className="border-red-200 bg-red-50 text-red-700">{item}</Badge>) : (
                      <span className="text-sm text-slate-500">Sin objeciones activas.</span>
                    )}
                  </div>
                </section>
              </TabsContent>

              <TabsContent value="timeline">
                <section className="rounded-lg border bg-white p-4 shadow-sm">
                  <div className="space-y-4">
                    {customer.timeline.map((event) => (
                      <div key={event.id} className="flex gap-3">
                        <span className="mt-1 h-2.5 w-2.5 rounded-full bg-blue-500" />
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-slate-900">{event.title}</div>
                          <div className="text-xs text-slate-500">{rel(event.created_at)} · {event.actor_type} · {event.event_type}</div>
                          {event.description && <p className="mt-1 text-sm text-slate-600">{event.description}</p>}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              </TabsContent>

              <TabsContent value="conversation">
                <section className="rounded-lg border bg-white p-4 shadow-sm">
                  <div className="space-y-3">
                    {customer.messages.map((message) => (
                      <div key={message.id} className={cn("max-w-[75%] rounded-lg p-3 text-sm", message.direction === "inbound" ? "bg-slate-100" : "ml-auto bg-blue-600 text-white")}>
                        <div className="mb-1 text-[11px] font-semibold opacity-70">{message.sender_type} · {rel(message.sent_at)}</div>
                        {message.body}
                        {message.confidence_score && <div className="mt-1 text-[11px] opacity-70">Confianza {Math.round(message.confidence_score * 100)}%</div>}
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 flex gap-2">
                    <Input value={messageText} onChange={(event) => setMessageText(event.target.value)} placeholder="Escribir seguimiento interno..." />
                    <Button disabled={!messageText.trim() || sendMessage.isPending} onClick={() => sendMessage.mutate()}>
                      <Send className="h-4 w-4" />
                    </Button>
                  </div>
                </section>
              </TabsContent>

              <TabsContent value="documents">
                <section className="overflow-hidden rounded-lg border bg-white shadow-sm">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-left text-xs text-slate-500">
                      <tr>
                        <th className="px-4 py-3">Documento</th>
                        <th className="px-4 py-3">Estado</th>
                        <th className="px-4 py-3">Uploaded</th>
                        <th className="px-4 py-3 text-right">Acción</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customer.documents.map((doc) => (
                        <tr key={doc.id} className="border-t">
                          <td className="px-4 py-3 font-medium">{doc.label}</td>
                          <td className="px-4 py-3">
                            <Badge variant="outline" className={doc.status === "missing" ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700"}>
                              {doc.status}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 text-slate-500">{doc.uploaded_at ? rel(doc.uploaded_at) : "-"}</td>
                          <td className="px-4 py-3 text-right">
                            <Button variant="outline" size="sm" onClick={() => patchDoc.mutate({ id: doc.id, status: doc.status === "approved" ? "missing" : "approved" })}>
                              {doc.status === "approved" ? "Reabrir" : "Aprobar"}
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              </TabsContent>

              <TabsContent value="risks">
                <div className="grid gap-3">
                  {customer.open_risks.map((risk) => (
                    <section key={risk.id} className="rounded-lg border bg-white p-4 shadow-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <Badge variant="outline" className={riskClass(risk.severity)}>{risk.severity}</Badge>
                          <h3 className="mt-2 text-sm font-semibold text-slate-900">{risk.risk_type.replaceAll("_", " ")}</h3>
                          <p className="mt-1 text-sm text-slate-600">{risk.reason}</p>
                        </div>
                        <AlertTriangle className="h-5 w-5 text-amber-500" />
                      </div>
                      <p className="mt-3 rounded-md bg-slate-50 p-3 text-xs text-slate-600">{risk.recommended_action}</p>
                    </section>
                  ))}
                  {customer.open_risks.length === 0 && <div className="rounded-lg border bg-white p-8 text-center text-sm text-slate-500">Sin riesgos abiertos.</div>}
                </div>
              </TabsContent>

              <TabsContent value="audit">
                <section className="rounded-lg border bg-white p-4 shadow-sm">
                  <div className="text-sm font-semibold">Audit trail</div>
                  <div className="mt-3 space-y-2 text-sm text-slate-600">
                    {customer.timeline.slice(0, 12).map((event) => (
                      <div key={event.id} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                        <span>{event.title}</span>
                        <span className="text-xs text-slate-500">{rel(event.created_at)}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </TabsContent>
            </Tabs>
          </section>

          <aside className="space-y-4">
            <section className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-900">Client Intelligence</h2>
                <Badge variant="outline">{stageLabel(customer.stage)}</Badge>
              </div>
              <div className="mt-4 grid gap-3 text-sm">
                <div className="flex items-center gap-2 text-slate-600"><Phone className="h-4 w-4" /> {customer.phone_e164}</div>
                <div className="flex items-center gap-2 text-slate-600"><MessageCircle className="h-4 w-4" /> {customer.conversation_count} conversaciones</div>
                <div className="flex items-center gap-2 text-slate-600"><CheckCircle2 className="h-4 w-4" /> {receivedDocs}/{customer.documents.length} documentos</div>
              </div>
              {customer.conversations[0] && (
                <Button className="mt-4 w-full" variant="outline" asChild>
                  <Link to="/conversations/$conversationId" params={{ conversationId: customer.conversations[0].id }}>
                    Abrir conversación
                  </Link>
                </Button>
              )}
            </section>

            <section className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <StickyNote className="h-4 w-4" />
                  Notas
                </h2>
                <Button variant="outline" size="sm" className="h-7 gap-1.5" onClick={() => setNoteOpen(true)}>
                  <Plus className="h-3.5 w-3.5" />
                  Nota
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                {(notes.data ?? []).slice(0, 6).map((note) => (
                  <div key={note.id} className="rounded-md border bg-slate-50 p-3 text-xs">
                    <p className="text-slate-700">{note.content}</p>
                    <div className="mt-1 text-slate-500">{note.author_email ?? "AtendIA"} · {rel(note.created_at)}</div>
                  </div>
                ))}
                {!notes.isLoading && (notes.data?.length ?? 0) === 0 && <div className="text-sm text-slate-500">Sin notas.</div>}
              </div>
            </section>

            <section className="rounded-lg border bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-900">AI review queue</h2>
              <div className="mt-3 space-y-2">
                {customer.ai_review_items.map((item) => (
                  <div key={item.id} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                    <div className="font-semibold">{item.title}</div>
                    <div className="mt-1">{item.description}</div>
                  </div>
                ))}
                {customer.ai_review_items.length === 0 && <div className="text-sm text-slate-500">Sin revisiones abiertas.</div>}
              </div>
            </section>
          </aside>
        </div>
      </main>

      <NewNoteDialog customerId={customerId} open={noteOpen} onOpenChange={setNoteOpen} />
    </div>
  );
}

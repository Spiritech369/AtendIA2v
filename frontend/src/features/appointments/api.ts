import { api } from "@/lib/api-client";

export type AppointmentStatus =
  | "scheduled"
  | "confirmed"
  | "arrived"
  | "completed"
  | "cancelled"
  | "no_show"
  | "rescheduled";

export type AppointmentType =
  | "test_drive"
  | "quote"
  | "documents"
  | "delivery"
  | "follow_up"
  | "financing"
  | "call";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface AppointmentItem {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  conversation_id: string | null;
  scheduled_at: string;
  ends_at: string | null;
  appointment_type: AppointmentType;
  service: string;
  status: AppointmentStatus;
  notes: string | null;
  timezone: string;
  source: string;
  advisor_id: string | null;
  advisor_name: string | null;
  vehicle_id: string | null;
  vehicle_label: string | null;
  ai_confidence: number | null;
  risk_score: number;
  risk_level: RiskLevel;
  risk_reasons: Array<{ code: string; message: string }>;
  recommended_actions: Array<{ code: string; label: string }>;
  credit_plan: string | null;
  down_payment_amount: number | null;
  down_payment_confirmed: boolean;
  documents_complete: boolean;
  last_customer_reply_at: string | null;
  confirmed_at: string | null;
  arrived_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  no_show_at: string | null;
  reminder_status: string;
  reminder_last_sent_at: string | null;
  action_log: Array<Record<string, unknown>>;
  created_by_type: string;
  created_at: string;
  updated_at: string;
  conflict_count: number;
}

export interface AppointmentConflict {
  id: string;
  scheduled_at: string;
  service: string;
  status: string;
}

export interface AppointmentCreate {
  customer_id: string;
  conversation_id?: string | null;
  scheduled_at: string;
  ends_at?: string | null;
  appointment_type?: AppointmentType;
  service: string;
  notes?: string | null;
  timezone?: string;
  source?: string;
  advisor_id?: string | null;
  advisor_name?: string | null;
  vehicle_id?: string | null;
  vehicle_label?: string | null;
  ai_confidence?: number | null;
  credit_plan?: string | null;
  down_payment_amount?: number | null;
  down_payment_confirmed?: boolean;
  documents_complete?: boolean;
  last_customer_reply_at?: string | null;
}

export interface AppointmentCreateResponse {
  appointment: AppointmentItem;
  conflicts: AppointmentConflict[];
}

export interface AppointmentListResponse {
  items: AppointmentItem[];
  total: number;
}

export interface AppointmentListParams {
  date_from?: string;
  date_to?: string;
  customer_id?: string;
  status?: string;
  limit?: number;
}

export interface AppointmentKpis {
  today: number;
  confirmed: number;
  high_risk: number;
  probable_no_show: number;
  missing_advisor: number;
  incomplete_docs: number;
  estimated_opportunity_mxn: number;
  this_week: number;
  conflicts: number;
  completed: number;
  live_at: string;
}

export interface PriorityItem {
  id: string;
  appointment_id: string;
  severity: RiskLevel | "low" | "medium" | "high" | "critical";
  reason: string;
  customer: string;
  time: string;
  vehicle: string | null;
  recommended_action: string;
  actions: string[];
}

export interface FunnelStage {
  stage: string;
  count: number;
  conversion: number;
  trend: number;
}

export interface OperationalConflict {
  appointment_id: string;
  related_appointment_id?: string;
  type: string;
  severity: string;
  message: string;
}

export interface SupervisorRecommendations {
  health: string;
  recommendations: Array<{ id: string; severity: string; title: string; detail: string; action: string }>;
  risks_today: number;
  open_slots: Array<{ advisor: string; time: string }>;
}

export interface NaturalParse {
  understood: boolean;
  confidence: number;
  date: string | null;
  time: string | null;
  appointment_type: AppointmentType;
  service: string;
  customer_name: string | null;
  customer_phone: string | null;
  vehicle_label: string | null;
  advisor_name: string | null;
  down_payment_amount: number | null;
  scheduled_at: string | null;
  ends_at: string | null;
  summary: string;
  missing_fields: string[];
}

export interface AdvisorOption {
  id: string;
  name: string;
  phone: string;
  max_per_day: number;
  close_rate: number;
}

export interface VehicleOption {
  id: string;
  label: string;
  status: string;
  available_for_test_drive: boolean;
}

export const appointmentsApi = {
  list: async (params: AppointmentListParams = {}) =>
    (await api.get<AppointmentListResponse>("/appointments", { params })).data,
  get: async (id: string) => (await api.get<AppointmentItem>(`/appointments/${id}`)).data,
  create: async (body: AppointmentCreate) =>
    (await api.post<AppointmentCreateResponse>("/appointments", body)).data,
  patch: async (id: string, body: Partial<AppointmentCreate> & { status?: AppointmentStatus }) =>
    (await api.patch<AppointmentItem>(`/appointments/${id}`, body)).data,
  delete: async (id: string) => api.delete(`/appointments/${id}`),
  kpis: async () => (await api.get<AppointmentKpis>("/appointments/kpis")).data,
  priorityFeed: async () => (await api.get<PriorityItem[]>("/appointments/priority-feed")).data,
  funnel: async () => (await api.get<FunnelStage[]>("/appointments/funnel")).data,
  conflicts: async (params: Pick<AppointmentListParams, "date_from" | "date_to"> = {}) =>
    (await api.get<OperationalConflict[]>("/appointments/conflicts", { params })).data,
  supervisor: async () => (await api.get<SupervisorRecommendations>("/appointments/supervisor-recommendations")).data,
  advisors: async () => (await api.get<AdvisorOption[]>("/appointments/advisors")).data,
  vehicles: async () => (await api.get<VehicleOption[]>("/appointments/vehicles")).data,
  parseNatural: async (text: string, timezone = "America/Mexico_City") =>
    (await api.post<NaturalParse>("/appointments/parse-natural-language", { text, timezone })).data,
  confirm: async (id: string) => (await api.post<AppointmentItem>(`/appointments/${id}/confirm`)).data,
  sendReminder: async (id: string) => (await api.post<AppointmentItem>(`/appointments/${id}/send-reminder`)).data,
  sendLocation: async (id: string) => (await api.post<AppointmentItem>(`/appointments/${id}/send-location`)).data,
  markArrived: async (id: string) => (await api.post<AppointmentItem>(`/appointments/${id}/mark-arrived`)).data,
  markCompleted: async (id: string) => (await api.post<AppointmentItem>(`/appointments/${id}/mark-completed`)).data,
  markNoShow: async (id: string) => (await api.post<AppointmentItem>(`/appointments/${id}/mark-no-show`)).data,
  reschedule: async (id: string, scheduled_at: string, ends_at?: string | null) =>
    (await api.post<AppointmentItem>(`/appointments/${id}/reschedule`, { scheduled_at, ends_at })).data,
  changeAdvisor: async (id: string, advisor_name: string, advisor_id?: string | null) =>
    (await api.post<AppointmentItem>(`/appointments/${id}/change-advisor`, { advisor_id, advisor_name })).data,
  changeVehicle: async (id: string, vehicle_label: string, vehicle_id?: string | null) =>
    (await api.post<AppointmentItem>(`/appointments/${id}/change-vehicle`, { vehicle_id, vehicle_label })).data,
  requestDocuments: async (id: string) =>
    (await api.post<AppointmentItem>(`/appointments/${id}/request-documents`)).data,
  createFollowUp: async (id: string, title = "Seguimiento posterior a cita") =>
    (await api.post<AppointmentItem>(`/appointments/${id}/create-follow-up`, { title })).data,
};

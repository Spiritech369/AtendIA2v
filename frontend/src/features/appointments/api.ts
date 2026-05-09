import { api } from "@/lib/api-client";

export interface AppointmentItem {
  id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  conversation_id: string | null;
  scheduled_at: string;
  service: string;
  status: string;
  notes: string | null;
  created_by_type: string;
  created_at: string;
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
  service: string;
  notes?: string | null;
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

export const appointmentsApi = {
  list: async (params: AppointmentListParams = {}) =>
    (await api.get<AppointmentListResponse>("/appointments", { params })).data,
  create: async (body: AppointmentCreate) =>
    (await api.post<AppointmentCreateResponse>("/appointments", body)).data,
  patch: async (id: string, body: Partial<AppointmentCreate> & { status?: string }) =>
    (await api.patch<AppointmentItem>(`/appointments/${id}`, body)).data,
  delete: async (id: string) => api.delete(`/appointments/${id}`),
};

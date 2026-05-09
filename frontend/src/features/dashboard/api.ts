import { api } from "@/lib/api-client";

export interface DashboardSummary {
  total_customers: number;
  conversations_today: number;
  active_conversations: number;
  unanswered_conversations: number;
  todays_appointments: Array<{
    id: string;
    customer_id: string;
    customer_name: string | null;
    customer_phone: string;
    scheduled_at: string;
    service: string;
    status: string;
  }>;
  recent_conversations: Array<{
    id: string;
    customer_id: string;
    customer_name: string | null;
    customer_phone: string;
    current_stage: string;
    last_activity_at: string;
    unread_count: number;
  }>;
  activity_chart: Array<{ date: string; inbound: number; outbound: number }>;
}

export const dashboardApi = {
  summary: async () => (await api.get<DashboardSummary>("/dashboard/summary")).data,
};

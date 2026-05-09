import { api } from "@/lib/api-client";

export interface NotificationItem {
  id: string;
  title: string;
  body: string | null;
  read: boolean;
  source_type: string | null;
  created_at: string;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  unread_count: number;
}

export const notificationsApi = {
  list: async () => (await api.get<NotificationListResponse>("/notifications")).data,
  markRead: async (id: string) =>
    (await api.patch<NotificationItem>(`/notifications/${id}/read`)).data,
  markAllRead: async () => (await api.post<{ updated: number }>("/notifications/read-all")).data,
};

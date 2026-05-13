import { api } from "@/lib/api-client";

export interface NavigationBadges {
  conversations_open: number;
  handoffs_open: number;
  handoffs_overdue: number;
  appointments_today: number;
  ai_debug_warnings: number;
  unread_notifications: number;
}

export const navigationApi = {
  getBadges: async (): Promise<NavigationBadges> =>
    (await api.get<NavigationBadges>("/navigation/badges")).data,
};

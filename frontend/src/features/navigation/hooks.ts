import { useQuery } from "@tanstack/react-query";

import { navigationApi } from "./api";

/**
 * Polls /navigation/badges every 30s — same cadence as notifications.
 * On error the query stays idle (data undefined) so the sidebar still
 * works without chips.
 */
export function useNavBadges() {
  return useQuery({
    queryKey: ["navigation", "badges"],
    queryFn: navigationApi.getBadges,
    refetchInterval: 30_000,
    retry: 1,
  });
}

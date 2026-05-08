import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  type HandoffListResponse,
  handoffsApi,
  type ListHandoffsParams,
} from "@/features/handoffs/api";

export function useHandoffs(filters: ListHandoffsParams = {}) {
  return useInfiniteQuery<HandoffListResponse, Error>({
    queryKey: ["handoffs", filters],
    queryFn: ({ pageParam }) =>
      handoffsApi.list({ ...filters, cursor: pageParam as string | null }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useAssignHandoff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, user_id }: { id: string; user_id: string }) =>
      handoffsApi.assign(id, user_id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["handoffs"] });
    },
  });
}

export function useResolveHandoff() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => handoffsApi.resolve(id, note),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["handoffs"] });
    },
  });
}

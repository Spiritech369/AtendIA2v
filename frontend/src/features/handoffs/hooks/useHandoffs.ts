import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  type HandoffListResponse,
  handoffsApi,
  type ListHandoffsParams,
} from "@/features/handoffs/api";
import { useCapabilitiesStore } from "@/stores/capabilities";

export function useHandoffs(filters: ListHandoffsParams = {}) {
  const demoMode = useCapabilitiesStore((s) => s.capabilities?.feature_flags.demo_mode === true);
  return useInfiniteQuery<HandoffListResponse, Error, InfiniteData<HandoffListResponse>>({
    queryKey: ["handoffs", filters, { demoMode }],
    queryFn: ({ pageParam }) =>
      handoffsApi.list({ ...filters, cursor: pageParam as string | null }),
    select: (data) =>
      demoMode
        ? data
        : {
            ...data,
            pages: data.pages.map((page) => ({
              ...page,
              items: page.items.filter((item) => item.payload?.source !== "mock"),
            })),
          },
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

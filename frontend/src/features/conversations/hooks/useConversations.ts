import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  type ConversationDetail,
  type ConversationListResponse,
  conversationsApi,
  type ListConversationsParams,
  type MessageListResponse,
} from "@/features/conversations/api";

export function useConversations(filters: ListConversationsParams = {}) {
  return useInfiniteQuery<ConversationListResponse, Error>({
    queryKey: ["conversations", filters],
    queryFn: ({ pageParam }) =>
      conversationsApi.list({ ...filters, cursor: pageParam as string | null }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useConversation(id: string) {
  return useQuery<ConversationDetail, Error>({
    queryKey: ["conversation", id],
    queryFn: () => conversationsApi.getOne(id),
    enabled: !!id,
  });
}

export function useMessages(conversationId: string) {
  return useInfiniteQuery<MessageListResponse, Error>({
    queryKey: ["messages", conversationId],
    queryFn: ({ pageParam }) =>
      conversationsApi.listMessages(conversationId, { cursor: pageParam as string | null }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: !!conversationId,
  });
}

import { useEffect, useRef } from "react";

/**
 * Generic auto-reconnecting WebSocket hook.
 *
 * - Exponential backoff on close (capped at 10s).
 * - Resets backoff on each successful open.
 * - Returns a `send` function for client→server messages (most operator
 *   flows are server→client only, but reserved for future use).
 *
 * Per-conversation and per-tenant flavors live in their respective feature
 * folders (e.g. `features/conversations/hooks/useConversationStream.ts`)
 * and call this hook with the right `path`.
 */
export interface WSEvent<T = unknown> {
  type: string;
  payload?: T;
  // Server-side schema includes ISO ts + conversation_id; expose as unknown
  // here and let feature hooks narrow.
  [k: string]: unknown;
}

export interface UseWebSocketOptions<E extends WSEvent = WSEvent> {
  path: string;
  onEvent: (e: E) => void;
  onOpen?: () => void;
  enabled?: boolean;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
}

export function useWebSocket<E extends WSEvent = WSEvent>(opts: UseWebSocketOptions<E>): void {
  const { path, onEvent, onOpen, enabled = true, initialBackoffMs = 1000, maxBackoffMs = 10_000 } = opts;
  const onEventRef = useRef(onEvent);
  const onOpenRef = useRef(onOpen);
  onEventRef.current = onEvent;
  onOpenRef.current = onOpen;

  useEffect(() => {
    if (!enabled) return;

    let ws: WebSocket | null = null;
    let backoff = initialBackoffMs;
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const wsUrl = (() => {
      // Path comes in like "/ws/tenants/abc". The dev server proxies /ws to
      // ws://localhost:8001 (vite.config). In prod the page is served from
      // the same FastAPI host so a relative URL upgraded to ws/wss works.
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${window.location.host}${path}`;
    })();

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(wsUrl);

      ws.onmessage = (m) => {
        try {
          const parsed = JSON.parse(m.data) as E;
          onEventRef.current(parsed);
        } catch {
          // Unparseable frames are dropped silently. The backend ought to
          // emit JSON; if a frame slips through we'd rather not crash the
          // hook on every malformed payload.
        }
      };

      ws.onopen = () => {
        backoff = initialBackoffMs;
        onOpenRef.current?.();
      };

      ws.onclose = () => {
        if (cancelled) return;
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, maxBackoffMs);
      };

      ws.onerror = () => {
        // Let onclose drive reconnection; close() also fires after error.
        ws?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      ws = null;
    };
  }, [path, enabled, initialBackoffMs, maxBackoffMs]);
}

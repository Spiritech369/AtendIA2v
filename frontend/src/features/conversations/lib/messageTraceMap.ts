/**
 * A14 — "Why did the agent say X". A turn trace is anchored to its
 * inbound (customer) message. The bot's reply(ies) belong to the same
 * turn, so we attribute every message from a turn's inbound message
 * (inclusive) up to the next turn's inbound message to that trace.
 *
 * Result: clicking the bot's outbound bubble opens the same DebugPanel
 * (agent + prompt + retrieval) that the inbound bubble already opened.
 * Pure + order-independent so it can be unit-tested without rendering.
 */

interface TraceAnchor {
  id: string;
  inbound_message_id: string | null;
  turn_number: number;
}

interface OrderedMessage {
  id: string;
  created_at: string;
}

export function buildMessageTraceMap(
  traces: TraceAnchor[],
  messages: OrderedMessage[],
): Map<string, string> {
  const map = new Map<string, string>();

  const sortedMsgs = messages
    .slice()
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const idxOf = new Map<string, number>();
  sortedMsgs.forEach((m, i) => idxOf.set(m.id, i));

  const anchors = traces
    .filter((t) => t.inbound_message_id !== null)
    .map((t) => ({
      traceId: t.id,
      idx: idxOf.get(t.inbound_message_id as string),
    }))
    .filter((a): a is { traceId: string; idx: number } => a.idx !== undefined)
    .sort((a, b) => a.idx - b.idx);

  if (anchors.length === 0) return map;

  let ai = 0;
  for (let i = anchors[0]!.idx; i < sortedMsgs.length; i++) {
    while (ai + 1 < anchors.length && anchors[ai + 1]!.idx <= i) ai++;
    map.set(sortedMsgs[i]!.id, anchors[ai]!.traceId);
  }
  return map;
}

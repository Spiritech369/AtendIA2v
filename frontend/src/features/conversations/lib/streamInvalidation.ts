/**
 * C11 — replace the 60s field-suggestions poll with a WS push.
 *
 * SUGGEST-tier field suggestions are created server-side during the
 * inbound turn that emits `message_received` (see
 * runner/ai_extraction_service.py — the SUGGEST path inserts rows but
 * emits no dedicated event). `field_extracted`/`field_updated` cover
 * the AUTO path. Invalidating the suggestions query on any of these
 * makes the panel refresh in realtime instead of up to 60s later.
 */
export function affectsFieldSuggestions(eventType: string): boolean {
  return (
    eventType === "message_received" ||
    eventType === "field_extracted" ||
    eventType === "field_updated"
  );
}

const AI_CONTEXT_RE = /\[AI_CONTEXT_SUMMARY][\s\S]*?\[\/AI_CONTEXT_SUMMARY]/g;
const IA_HEADER_RE = /Resumen IA del historial:\s*/g;
const EXCESS_NEWLINES_RE = /\n{3,}/g;

export function cleanInternalNotes(value: unknown): string {
  return String(value ?? "")
    .replace(AI_CONTEXT_RE, "")
    .replace(IA_HEADER_RE, "")
    .replace(EXCESS_NEWLINES_RE, "\n\n")
    .trim();
}

const SKIPPED_CONTENT = new Set(["[imagen]", "[audio]", "[documento]", "[video]"]);

export function shouldSkipText(text: string, hasMedia: boolean): boolean {
  return hasMedia && SKIPPED_CONTENT.has(text.trim());
}

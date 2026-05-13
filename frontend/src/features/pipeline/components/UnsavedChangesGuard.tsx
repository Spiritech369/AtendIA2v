/**
 * M5 of the pipeline-automation editor plan.
 *
 * Hook + null-rendering component that mounts a `beforeunload` listener
 * while there are unsaved local pipeline edits. The browser shows its
 * native "Reload site? Changes you made may not be saved." prompt on
 * navigation away. Doesn't render any DOM.
 *
 * Note: tanstack-router doesn't ship a built-in `onLeave` hook, so we
 * cover the most common loss scenario (full reload, tab close,
 * navigation typed into the URL bar) and leave in-app SPA navigation to
 * future iteration. That's the 90% case for QA flows.
 */
import { useEffect } from "react";

export function UnsavedChangesGuard({ dirty }: { dirty: boolean }) {
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      // Required by the spec for the prompt to actually show. Modern
      // browsers ignore the returnValue string but still gate on it
      // being non-empty (or preventDefault being called).
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  return null;
}

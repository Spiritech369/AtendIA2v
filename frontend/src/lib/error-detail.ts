/**
 * Normalise a FastAPI/Pydantic error response to a single string.
 *
 * FastAPI returns three shapes:
 * - HTTPException: ``{"detail": "Some message"}`` — string.
 * - Pydantic validation (422): ``{"detail": [{"type", "loc", "msg", "input", "ctx"}]}``
 *   — array of structured error objects.
 * - Anything else / network failure: caller's fallback.
 *
 * Before this helper, frontend code typed ``detail`` as ``string`` and passed
 * it straight to React (toast description, FormMessage). When Pydantic
 * returned an array, React threw "Objects are not valid as a React child
 * (found: object with keys {type, loc, msg, input, ctx})".
 */
export function extractErrorDetail(err: unknown, fallback = ""): string {
  // axios error shape: err.response.data.detail
  // fetch error shape: err.body.detail
  // Either way, find ``detail``.
  type DetailItem = {
    msg?: string;
    loc?: unknown;
    type?: string;
  };
  const e = err as {
    response?: { data?: { detail?: unknown } };
    data?: { detail?: unknown };
    detail?: unknown;
    message?: string;
  };
  const detail =
    e?.response?.data?.detail ?? e?.data?.detail ?? e?.detail ?? null;

  if (typeof detail === "string" && detail.length > 0) {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const item = d as DetailItem;
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((p) => p !== "body").join(".")
          : "";
        const msg = item.msg ?? "";
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean)
      .join("; ") || fallback;
  }
  if (detail && typeof detail === "object") {
    const obj = detail as {
      summary?: string;
      issues?: Array<{ message?: string; path?: string }>;
    };
    if (typeof obj.summary === "string" && obj.summary.length > 0) {
      const issueText = Array.isArray(obj.issues)
        ? obj.issues
            .slice(0, 3)
            .map((issue) =>
              issue.message
                ? `${issue.path ? `${issue.path}: ` : ""}${issue.message}`
                : "",
            )
            .filter(Boolean)
            .join("; ")
        : "";
      return issueText ? `${obj.summary}: ${issueText}` : obj.summary;
    }
  }
  if (typeof e?.message === "string" && e.message.length > 0) {
    return e.message;
  }
  return fallback;
}

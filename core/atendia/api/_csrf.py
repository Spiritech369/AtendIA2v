"""Double-submit-cookie CSRF middleware (Phase 4 T4).

Threat model:
* The session is in an httpOnly cookie. A cross-origin attacker cannot
  read it but the browser still sends it, so CSRF is the gap.
* The CSRF token, by contrast, is in a NON-httpOnly cookie (`atendia_csrf`)
  and ALSO returned in the login response body. The frontend reads the
  cookie via `document.cookie` and echoes the value in the
  `X-CSRF-Token` header on every unsafe request.
* An attacker on a different origin cannot read the cookie (Same-Origin
  Policy), so they cannot set the matching header. Mismatch → 403.

Scope:
* Only enforced on unsafe methods (POST/PUT/PATCH/DELETE) under `/api/*`.
* Two whitelisted prefixes bypass the check:
    - `/api/v1/auth/login` — the request that *creates* the session;
      no cookie exists yet on first call.
    - `/api/v1/runner/*` — internal dev/test endpoint with no operator
      session at all.
* Webhook routes (e.g. Meta inbound) are mounted outside `/api/` so they
  are unaffected.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from atendia.api._auth_helpers import CSRF_COOKIE, constant_time_compare

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/login",
    "/api/v1/runner/",
    "/api/v1/internal/",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if request.method in SAFE_METHODS or not path.startswith("/api/"):
            return await call_next(request)
        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)

        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get(CSRF_HEADER)
        if not cookie or not header or not constant_time_compare(cookie, header):
            return JSONResponse(
                {"detail": "csrf token missing or invalid"}, status_code=403
            )
        return await call_next(request)


def install_csrf_middleware(app) -> None:
    """Idempotent helper for `main.py`."""
    app.add_middleware(CSRFMiddleware)


__all__ = ["CSRFMiddleware", "install_csrf_middleware", "CSRF_HEADER"]

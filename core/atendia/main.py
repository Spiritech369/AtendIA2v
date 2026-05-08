from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from atendia.api._auth_helpers import assert_prod_secret_safety
from atendia.api._csrf import install_csrf_middleware
from atendia.api.analytics_routes import router as analytics_router
from atendia.api.audit_log_routes import router as audit_log_router
from atendia.api.auth_routes import router as auth_router
from atendia.api.conversations_routes import router as conversations_router
from atendia.api.customers_routes import router as customers_router
from atendia.api.exports_routes import router as exports_router
from atendia.api.handoffs_routes import router as handoffs_router
from atendia.api.runner_routes import router as runner_router
from atendia.api.tenants_routes import router as tenants_router
from atendia.api.turn_traces_routes import router as turn_traces_router
from atendia.api.users_routes import router as users_router
from atendia.realtime.ws_routes import router as ws_router
from atendia.tools import register_all_tools
from atendia.webhooks.meta_routes import router as meta_webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_prod_secret_safety()
    register_all_tools()
    yield


app = FastAPI(title="atendia-core", version="0.1.0", lifespan=lifespan)
install_csrf_middleware(app)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(
    conversations_router, prefix="/api/v1/conversations", tags=["conversations"]
)
app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(customers_router, prefix="/api/v1/customers", tags=["customers"])
app.include_router(exports_router, prefix="/api/v1/exports", tags=["exports"])
app.include_router(handoffs_router, prefix="/api/v1/handoffs", tags=["handoffs"])
app.include_router(tenants_router, prefix="/api/v1/tenants", tags=["tenants"])
app.include_router(
    turn_traces_router, prefix="/api/v1/turn-traces", tags=["turn-traces"]
)
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(audit_log_router, prefix="/api/v1/audit-log", tags=["audit-log"])
app.include_router(runner_router, prefix="/api/v1")
app.include_router(meta_webhook_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# Phase 4 T59 — serve the built React SPA from FastAPI in production.
#
# Path resolves to `<repo>/frontend/dist/` from the package layout
# `<repo>/core/atendia/main.py`. We mount this LAST so /api, /ws, and
# /health win their routing match first. `html=True` makes StaticFiles
# fall back to index.html on any unknown path — that's what TanStack
# Router needs for client-side deep links.
#
# Skipped silently when dist/ doesn't exist so dev runs (no `pnpm build`)
# don't crash on startup.
_FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
)
if _FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )

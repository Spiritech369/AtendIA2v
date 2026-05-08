from contextlib import asynccontextmanager

from fastapi import FastAPI

from atendia.api._auth_helpers import assert_prod_secret_safety
from atendia.api._csrf import install_csrf_middleware
from atendia.api.auth_routes import router as auth_router
from atendia.api.conversations_routes import router as conversations_router
from atendia.api.customers_routes import router as customers_router
from atendia.api.handoffs_routes import router as handoffs_router
from atendia.api.runner_routes import router as runner_router
from atendia.api.tenants_routes import router as tenants_router
from atendia.api.turn_traces_routes import router as turn_traces_router
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
app.include_router(customers_router, prefix="/api/v1/customers", tags=["customers"])
app.include_router(handoffs_router, prefix="/api/v1/handoffs", tags=["handoffs"])
app.include_router(tenants_router, prefix="/api/v1/tenants", tags=["tenants"])
app.include_router(
    turn_traces_router, prefix="/api/v1/turn-traces", tags=["turn-traces"]
)
app.include_router(runner_router, prefix="/api/v1")
app.include_router(meta_webhook_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

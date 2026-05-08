from contextlib import asynccontextmanager

from fastapi import FastAPI

from atendia.api.auth_routes import router as auth_router
from atendia.api.runner_routes import router as runner_router
from atendia.realtime.ws_routes import router as ws_router
from atendia.tools import register_all_tools
from atendia.webhooks.meta_routes import router as meta_webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    register_all_tools()
    yield


app = FastAPI(title="atendia-core", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(runner_router, prefix="/api/v1")
app.include_router(meta_webhook_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

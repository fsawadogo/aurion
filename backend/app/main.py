"""Aurion Clinical AI — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.admin import router as admin_router
from app.api.v1.export import router as export_router
from app.api.v1.health import router as health_router
from app.api.v1.notes import router as notes_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.transcription import router as transcription_router
from app.api.v1.vision import router as vision_router
from app.api.v1.websocket import router as ws_router
from app.core.database import close_db, init_db
from app.core.logging import setup_logging
from app.modules.config.appconfig_client import get_appconfig_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    await init_db()
    appconfig = get_appconfig_client()
    await appconfig.start_polling()
    yield
    # Shutdown
    await appconfig.stop_polling()
    await close_db()


app = FastAPI(
    title="Aurion Clinical AI",
    description="Wearable multimodal AI physician assistant — Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(admin_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(transcription_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(vision_router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")
app.include_router(ws_router)

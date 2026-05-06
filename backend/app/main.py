"""Aurion Clinical AI — FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.auth import seed_dev_users
from app.api.v1.config import router as config_router
from app.api.v1.export import router as export_router
from app.api.v1.frames import router as frames_router
from app.api.v1.health import router as health_router
from app.api.v1.notes import router as notes_router
from app.api.v1.privacy import router as privacy_router
from app.api.v1.profile import router as profile_router
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
    await seed_dev_users()
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

_allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(privacy_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(transcription_router, prefix="/api/v1")
app.include_router(frames_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(vision_router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")
app.include_router(ws_router)

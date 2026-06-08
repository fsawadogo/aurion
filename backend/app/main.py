"""Aurion Clinical AI — FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.auth import seed_dev_users
from app.api.v1.clips import router as clips_router
from app.api.v1.config import router as config_router
from app.api.v1.export import router as export_router
from app.api.v1.frames import router as frames_router
from app.api.v1.health import router as health_router
from app.api.v1.me import router as me_router
from app.api.v1.me_prompts import router as me_prompts_router
from app.api.v1.me_security import router as me_security_router
from app.api.v1.notes import router as notes_router
from app.api.v1.privacy import router as privacy_router
from app.api.v1.profile import router as profile_router
from app.api.v1.screen import router as screen_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.transcription import router as transcription_router
from app.api.v1.vision import router as vision_router
from app.api.v1.websocket import router as ws_router
from app.core.database import close_db
from app.core.logging import setup_logging
from app.modules.config.appconfig_client import get_appconfig_client
from app.modules.config.provider_overrides import (
    start_override_polling,
    stop_override_polling,
)
from app.modules.emr.worker import start_worker as start_emr_worker
from app.modules.emr.worker import stop_worker as stop_emr_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup. Schema is owned by alembic — migrations run via the container
    # entrypoint before this code is reached.
    setup_logging()
    await seed_dev_users()
    appconfig = get_appconfig_client()
    await appconfig.start_polling()
    await start_override_polling()
    # EMR retry worker — opt-in via AURION_EMR_RETRY_WORKER_ENABLED.
    # No-op when disabled, so safe to call unconditionally.
    await start_emr_worker()
    yield
    # Shutdown — reverse order. EMR worker first so an in-flight
    # drain pass can finish before the DB connection closes.
    await stop_emr_worker()
    await stop_override_polling()
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

_errors_logger = logging.getLogger("aurion.api.errors")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all 500 handler that keeps CORS headers on error responses.

    Starlette routes a handler keyed on ``Exception`` through
    ``ServerErrorMiddleware``, which sits OUTSIDE ``CORSMiddleware`` — so the
    response never passes back through CORS and would otherwise ship with no
    ``Access-Control-Allow-Origin`` header. A browser then masks the real 500
    as a CORS failure. We re-apply the CORS headers manually here, mirroring
    ``CORSMiddleware``'s ``allow_credentials=True`` (origin echo, never ``*``
    alongside credentials).

    The body is a fixed generic string — no exception message, no traceback —
    so PHI can never leak into an API response. The real error (PHI-free:
    method, path, and exception class only) is logged server-side via
    ``logger.exception`` for CloudWatch.
    """
    _errors_logger.exception(
        "Unhandled exception: method=%s path=%s error=%s",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
    origin = request.headers.get("origin")
    if origin and (origin in _allowed_origins or "*" in _allowed_origins):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profile_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(privacy_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(transcription_router, prefix="/api/v1")
app.include_router(frames_router, prefix="/api/v1")
app.include_router(clips_router, prefix="/api/v1")
app.include_router(screen_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(me_prompts_router, prefix="/api/v1")
app.include_router(me_security_router, prefix="/api/v1")
app.include_router(vision_router, prefix="/api/v1")
app.include_router(export_router, prefix="/api/v1")
app.include_router(ws_router)

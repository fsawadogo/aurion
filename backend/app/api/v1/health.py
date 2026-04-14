"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.config.appconfig_client import get_config

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    config = get_config()
    return {
        "status": "ok",
        "version": "0.1.0",
        "providers": config.providers.model_dump(),
    }

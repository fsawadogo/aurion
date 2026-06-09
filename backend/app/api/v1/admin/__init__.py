"""Admin API package — aggregates user, audit, sessions, eval, metrics routers.

``main.py`` continues to import ``from app.api.v1.admin import router as admin_router``
— the package re-exports a single ``router`` that mounts all five
sub-routers under the same ``/admin`` prefix. No URL changes vs. the
pre-split monolithic file.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin import (
    alerts,
    analytics,
    audit,
    compliance,
    config,
    emr,
    eval,
    feature_flags,
    media,
    metrics,
    probe,
    providers,
    sessions,
    templates,
    users,
)

router = APIRouter()
router.include_router(users.router)
router.include_router(audit.router)
router.include_router(sessions.router)
router.include_router(eval.router)
router.include_router(metrics.router)
router.include_router(config.router)
router.include_router(alerts.router)
router.include_router(templates.router)
router.include_router(providers.router)
router.include_router(compliance.router)
router.include_router(emr.router)
router.include_router(probe.router)
router.include_router(feature_flags.router)
router.include_router(media.router)
router.include_router(analytics.router)

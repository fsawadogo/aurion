"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.config.appconfig_client import get_config

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    config = get_config()
    flags = config.feature_flags
    body = {
        "status": "ok",
        "version": "0.1.0",
        "providers": config.providers.model_dump(),
    }
    # Only meaningful when video import is on, and only then worth the one-time
    # cost of loading the detectors. Import is function-local so a deployment
    # without OpenCV (or with the feature off) never pays for cv2 at import time.
    if flags.video_import_enabled:
        try:
            from app.modules.video_import.masking import detector_status

            body["masking"] = detector_status()
        except Exception:  # noqa: BLE001 — diagnostics must never fail /health
            body["masking"] = {"error": "unavailable"}
        # The three gates that decide whether an imported clip yields any visual
        # enrichment at all. Surfaced together because a note can come back
        # empty-but-successful when any one of them is off, and they are
        # otherwise invisible without AppConfig access.
        body["video_import"] = {
            "standalone_visual": flags.visual_evidence_standalone_enabled,
            "drop_zero_face_frames": flags.video_import_drop_zero_face_frames,
            "cadence_seconds": config.pipeline.video_import_cadence_seconds,
        }
    return body

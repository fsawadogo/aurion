"""Config API route — exposes AppConfig values relevant to the iOS client.

Returns a sanitized subset of the AppConfig document. Provider keys are
included so the client can show which provider produced a given note.
Pipeline timing and feature flags are included so the client can honour
them without redeploy.

Secrets and AWS-only knobs (e.g. provider API keys, AppConfig version
metadata) are NEVER returned by this endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.modules.auth.service import CurrentUser, get_current_user
from app.modules.config.appconfig_client import get_config

router = APIRouter(prefix="/config", tags=["config"])


class ProvidersResponse(BaseModel):
    transcription: str
    note_generation: str
    vision: str


class PipelineResponse(BaseModel):
    stage1_skip_window_seconds: int
    frame_window_clinic_ms: int
    frame_window_procedural_ms: int
    screen_capture_fps: int
    video_capture_fps: int


class FeatureFlagsResponse(BaseModel):
    screen_capture_enabled: bool
    note_versioning_enabled: bool
    session_pause_resume_enabled: bool
    per_session_provider_override: bool
    meta_wearables_enabled: bool


class ClientConfigResponse(BaseModel):
    providers: ProvidersResponse
    pipeline: PipelineResponse
    feature_flags: FeatureFlagsResponse


@router.get("", response_model=ClientConfigResponse)
async def get_client_config(_: CurrentUser = Depends(get_current_user)):
    """Return the subset of AppConfig that iOS clients need."""
    cfg = get_config()
    return ClientConfigResponse(
        providers=ProvidersResponse(
            transcription=cfg.providers.transcription.value,
            note_generation=cfg.providers.note_generation.value,
            vision=cfg.providers.vision.value,
        ),
        pipeline=PipelineResponse(
            stage1_skip_window_seconds=cfg.pipeline.stage1_skip_window_seconds,
            frame_window_clinic_ms=cfg.pipeline.frame_window_clinic_ms,
            frame_window_procedural_ms=cfg.pipeline.frame_window_procedural_ms,
            screen_capture_fps=cfg.pipeline.screen_capture_fps,
            video_capture_fps=cfg.pipeline.video_capture_fps,
        ),
        feature_flags=FeatureFlagsResponse(
            screen_capture_enabled=cfg.feature_flags.screen_capture_enabled,
            note_versioning_enabled=cfg.feature_flags.note_versioning_enabled,
            session_pause_resume_enabled=cfg.feature_flags.session_pause_resume_enabled,
            per_session_provider_override=cfg.feature_flags.per_session_provider_override,
            meta_wearables_enabled=cfg.feature_flags.meta_wearables_enabled,
        ),
    )

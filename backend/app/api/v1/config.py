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
    # ── Clip family (#324) ─────────────────────────────────────────────
    # iOS owns the during-recording cadence timer AND gates it on the
    # resolved visual-evidence mode, so BOTH must reach the device: the
    # cadence driver only starts when `clip_cadence_seconds > 0` AND the
    # mode is clips_only/hybrid (see iOS SessionManager.clipCadenceActive).
    # Emitting `clip_cadence_seconds` alone — with `visual_evidence_mode`
    # withheld — left iOS defaulting the mode to `frames_only`, so cadence
    # never activated and every session produced zero clips. We therefore
    # emit the whole clip family the iOS client decodes. dev: mode=hybrid,
    # cadence=30; pilot default: mode=frames_only, cadence=0.
    clip_cadence_seconds: int
    visual_evidence_mode: str
    clip_window_ms: int
    clip_trigger_kinds: list[str]


class FeatureFlagsResponse(BaseModel):
    screen_capture_enabled: bool
    note_versioning_enabled: bool
    session_pause_resume_enabled: bool
    per_session_provider_override: bool
    meta_wearables_enabled: bool
    # ── Video-vision master gates (lane-backend/vision-evidence-feature-flags)
    # Two on/off master switches for the patient video-vision paths.
    # Exposed for parity so iOS can reflect which path(s) the operator has
    # enabled. Distinct from `screen_capture_enabled` (frame-by-frame
    # screen OCR).
    clip_video_interpretation_enabled: bool
    frame_by_frame_video_enabled: bool
    # ── Post-pilot card visibility (lane-full/card-visibility-flags) ──────
    # Four post-pilot scaffolding cards on the iOS note-review screen.
    # All default False on the schema; ADMIN flips per-card via the
    # /admin/feature-flags endpoint and iOS gates each card render on
    # the corresponding flag (and skips the card's own GET on hidden).
    orders_card_enabled: bool
    coding_card_enabled: bool
    patient_summary_card_enabled: bool
    emr_writeback_card_enabled: bool
    # ── In-encounter visual measurement (#63) ────────────────────────────
    # Master gate for the iOS AR measurement instrument (wound L/W + ROM).
    # Ships dark; the instrument stays hidden until ADMIN flips this. iOS
    # defaults it False when absent, so older clients are unaffected.
    measurement_enabled: bool


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
            clip_cadence_seconds=cfg.pipeline.clip_cadence_seconds,
            visual_evidence_mode=cfg.pipeline.visual_evidence_mode.value,
            clip_window_ms=cfg.pipeline.clip_window_ms,
            clip_trigger_kinds=cfg.pipeline.clip_trigger_kinds,
        ),
        feature_flags=FeatureFlagsResponse(
            screen_capture_enabled=cfg.feature_flags.screen_capture_enabled,
            note_versioning_enabled=cfg.feature_flags.note_versioning_enabled,
            session_pause_resume_enabled=cfg.feature_flags.session_pause_resume_enabled,
            per_session_provider_override=cfg.feature_flags.per_session_provider_override,
            meta_wearables_enabled=cfg.feature_flags.meta_wearables_enabled,
            clip_video_interpretation_enabled=cfg.feature_flags.clip_video_interpretation_enabled,
            frame_by_frame_video_enabled=cfg.feature_flags.frame_by_frame_video_enabled,
            orders_card_enabled=cfg.feature_flags.orders_card_enabled,
            coding_card_enabled=cfg.feature_flags.coding_card_enabled,
            patient_summary_card_enabled=cfg.feature_flags.patient_summary_card_enabled,
            emr_writeback_card_enabled=cfg.feature_flags.emr_writeback_card_enabled,
            measurement_enabled=cfg.feature_flags.measurement_enabled,
        ),
    )

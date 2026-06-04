"""Pydantic schema for Aurion AppConfig document.

Validates the full AppConfig JSON structure. Invalid provider keys
or missing required fields fail before reaching the application.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ── Provider Key Enums ─────────────────────────────────────────────────────

class TranscriptionProviderKey(str, Enum):
    WHISPER = "whisper"
    ASSEMBLYAI = "assemblyai"


class NoteGenerationProviderKey(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class VisionProviderKey(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


# Dual-mode visual evidence (see docs/plans/p1-1-clip-evidence-schema.md).
# `FRAMES_ONLY` is the default — current pilot behavior is preserved. The
# eval team flips per-session to `CLIPS_ONLY` for evaluation runs; `HYBRID`
# routes per-trigger-kind (motion / rom / gait / procedural → clip; static
# observations → frame).
class VisualEvidenceMode(str, Enum):
    FRAMES_ONLY = "frames_only"
    CLIPS_ONLY = "clips_only"
    HYBRID = "hybrid"


# ── Config Sub-Models ──────────────────────────────────────────────────────

class ProvidersConfig(BaseModel):
    transcription: TranscriptionProviderKey = TranscriptionProviderKey.WHISPER
    note_generation: NoteGenerationProviderKey = NoteGenerationProviderKey.ANTHROPIC
    vision: VisionProviderKey = VisionProviderKey.OPENAI
    # Frame providers (static-image) and clip providers (native video) are
    # routed independently. Gemini is the only frontier model with native
    # video-clip understanding today, so it's the default clip provider;
    # OpenAI and Anthropic fall back to midpoint-still extraction (P1-2).
    vision_clip: VisionProviderKey = VisionProviderKey.GEMINI


class NoteGenerationModelParams(BaseModel):
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=100, le=16000)


class VisionModelParams(BaseModel):
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=100, le=4000)
    confidence_threshold: Literal["low", "medium", "high"] = "medium"


class ModelParamsConfig(BaseModel):
    note_generation: NoteGenerationModelParams = Field(default_factory=NoteGenerationModelParams)
    vision: VisionModelParams = Field(default_factory=VisionModelParams)


class PipelineConfig(BaseModel):
    stage1_skip_window_seconds: int = Field(default=60, ge=10, le=600)
    frame_window_clinic_ms: int = Field(default=3000, ge=500, le=30000)
    frame_window_procedural_ms: int = Field(default=7000, ge=1000, le=60000)
    screen_capture_fps: int = Field(default=2, ge=1, le=10)
    video_capture_fps: int = Field(default=1, ge=1, le=10)
    # ── Dual-mode visual evidence ──────────────────────────────────────
    # Default `FRAMES_ONLY` so every existing call site is byte-identical
    # to today's pilot build. The eval team flips per-session via the
    # `per_session_visual_evidence_mode_override` feature flag.
    visual_evidence_mode: VisualEvidenceMode = VisualEvidenceMode.FRAMES_ONLY
    # Clip extraction window — 7s default matches the procedural frame
    # window for parity with the existing static path. iOS encodes this
    # many ms of H.264 around each motion trigger.
    clip_window_ms: int = Field(default=7000, ge=1000, le=30000)
    # Ring buffer holding raw `CMSampleBuffer` references in iOS. Sized
    # comfortably above the clip window so a trigger landing late still
    # has enough pre-roll. ~30 MB peak for 15s @ 720p on A15+.
    clip_ring_buffer_seconds: int = Field(default=15, ge=5, le=60)
    # In `HYBRID` mode, triggers whose `kind` is in this list route to the
    # clip path; everything else stays on the frame path. Defaults are the
    # motion-heavy clinical use cases — ROM, gait, surgical/procedural
    # technique. Visual trigger classifier populates `kind` from the
    # transcript segment; see modules/note_gen/trigger_classifier.
    clip_trigger_kinds: list[str] = Field(
        default_factory=lambda: ["motion", "rom", "gait", "procedural"]
    )
    # ── Longitudinal patient context (#61, full slice) ─────────────────
    # Cap on the number of prior encounters the Stage 1 note-gen
    # pipeline feeds into the LLM prompt as context. Three is the
    # default — it's enough to surface "the last visit", "the visit
    # before that", and one more for trend-without-trajectory framing,
    # while staying well inside the LLM's input budget for the pre-
    # transcript header. The eval team can dial this up to 10 (per the
    # schema bound) to test how the model behaves with a richer
    # history; below 1 makes the lookup pointless (would never include
    # any encounters).
    longitudinal_context_max_encounters: int = Field(default=3, ge=1, le=10)


class FeatureFlagsConfig(BaseModel):
    # Off for the pilot — see infrastructure/appconfig.tf. This is only the
    # fallback used when AppConfig is unreachable; the live AppConfig value
    # is the runtime source of truth.
    screen_capture_enabled: bool = False
    note_versioning_enabled: bool = True
    session_pause_resume_enabled: bool = True
    per_session_provider_override: bool = True
    # Gates the Meta Wearables Device Access Toolkit integration. Off until
    # Meta partner approval lands; flipping this on requires the iOS bundle
    # to be signed by an approved partner team.
    meta_wearables_enabled: bool = False
    # Eval-team can flip `visual_evidence_mode` per-session for evaluation
    # runs even when the pilot-wide default is `FRAMES_ONLY`. Mirrors the
    # `per_session_provider_override` pattern.
    per_session_visual_evidence_mode_override: bool = True


# ── Root AppConfig Schema ──────────────────────────────────────────────────

class AppConfigSchema(BaseModel):
    """Full AppConfig document schema.

    Validates the entire configuration document. Any invalid provider key,
    out-of-range parameter, or missing field fails Pydantic validation
    before the config reaches the application.
    """

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    model_params: ModelParamsConfig = Field(default_factory=ModelParamsConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    feature_flags: FeatureFlagsConfig = Field(default_factory=FeatureFlagsConfig)

    @model_validator(mode="after")
    def validate_frame_windows(self) -> "AppConfigSchema":
        if self.pipeline.frame_window_procedural_ms < self.pipeline.frame_window_clinic_ms:
            raise ValueError(
                "frame_window_procedural_ms must be >= frame_window_clinic_ms"
            )
        return self

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


# ── Config Sub-Models ──────────────────────────────────────────────────────

class ProvidersConfig(BaseModel):
    transcription: TranscriptionProviderKey = TranscriptionProviderKey.WHISPER
    note_generation: NoteGenerationProviderKey = NoteGenerationProviderKey.ANTHROPIC
    vision: VisionProviderKey = VisionProviderKey.OPENAI


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


class FeatureFlagsConfig(BaseModel):
    screen_capture_enabled: bool = True
    note_versioning_enabled: bool = True
    session_pause_resume_enabled: bool = True
    per_session_provider_override: bool = True


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

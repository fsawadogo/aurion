"""Tests for AppConfig Pydantic schema validation."""

import pytest
from pydantic import ValidationError

from app.modules.config.schema import (
    AppConfigSchema,
    FeatureFlagsConfig,
    ModelVersionsConfig,
    NoteGenerationProviderKey,
    PipelineConfig,
    ProvidersConfig,
    TranscriptionProviderKey,
    VisionModelParams,
    VisionProviderKey,
)


class TestProvidersConfig:
    def test_defaults(self):
        config = ProvidersConfig()
        assert config.transcription == TranscriptionProviderKey.WHISPER
        assert config.note_generation == NoteGenerationProviderKey.ANTHROPIC
        assert config.vision == VisionProviderKey.OPENAI

    def test_valid_keys(self):
        config = ProvidersConfig(
            transcription="assemblyai",
            note_generation="gemini",
            vision="anthropic",
        )
        assert config.transcription == TranscriptionProviderKey.ASSEMBLYAI
        assert config.note_generation == NoteGenerationProviderKey.GEMINI
        assert config.vision == VisionProviderKey.ANTHROPIC

    def test_invalid_transcription_key_rejected(self):
        with pytest.raises(ValidationError):
            ProvidersConfig(transcription="invalid_provider")

    def test_invalid_note_gen_key_rejected(self):
        with pytest.raises(ValidationError):
            ProvidersConfig(note_generation="invalid_provider")

    def test_invalid_vision_key_rejected(self):
        with pytest.raises(ValidationError):
            ProvidersConfig(vision="invalid_provider")


class TestPipelineConfig:
    def test_defaults(self):
        config = PipelineConfig()
        assert config.stage1_skip_window_seconds == 60
        assert config.frame_window_clinic_ms == 3000
        assert config.frame_window_procedural_ms == 7000

    def test_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            PipelineConfig(stage1_skip_window_seconds=5)  # min is 10

    def test_media_review_retention_days_default(self):
        # #338 — windowed media retention. Default 7 days.
        config = PipelineConfig()
        assert config.media_review_retention_days == 7

    def test_media_review_retention_days_bounds(self):
        # Bounds 1..30 MUST match the AppConfig JSON-Schema validator the
        # infra lane adds — both ends are exclusive failures.
        assert PipelineConfig(media_review_retention_days=1).media_review_retention_days == 1
        assert PipelineConfig(media_review_retention_days=30).media_review_retention_days == 30
        with pytest.raises(ValidationError):
            PipelineConfig(media_review_retention_days=0)  # min is 1
        with pytest.raises(ValidationError):
            PipelineConfig(media_review_retention_days=31)  # max is 30

    def test_clip_cadence_seconds_default_off(self):
        # #324 — cadence floor defaults OFF (0) for back-compat: today's
        # pilot produces clips only at spoken-keyword triggers.
        config = PipelineConfig()
        assert config.clip_cadence_seconds == 0

    def test_clip_cadence_seconds_bounds(self):
        # Bounds 0..300 MUST match the AppConfig JSON-Schema validator in
        # infrastructure/appconfig.tf. dev runs at 30.
        assert PipelineConfig(clip_cadence_seconds=0).clip_cadence_seconds == 0
        assert PipelineConfig(clip_cadence_seconds=30).clip_cadence_seconds == 30
        assert PipelineConfig(clip_cadence_seconds=300).clip_cadence_seconds == 300
        with pytest.raises(ValidationError):
            PipelineConfig(clip_cadence_seconds=-1)  # min is 0
        with pytest.raises(ValidationError):
            PipelineConfig(clip_cadence_seconds=301)  # max is 300


class TestFeatureFlagsConfig:
    def test_media_review_retention_disabled_by_default(self):
        # #338 — PHI-sensitive feature ships dark. Default OFF so OFF
        # behavior is byte-identical to today.
        config = FeatureFlagsConfig()
        assert config.media_review_retention_enabled is False

    def test_media_review_retention_can_be_enabled(self):
        config = FeatureFlagsConfig(media_review_retention_enabled=True)
        assert config.media_review_retention_enabled is True


class TestAppConfigSchema:
    def test_full_valid_config(self):
        raw = {
            "providers": {
                "transcription": "whisper",
                "note_generation": "anthropic",
                "vision": "openai",
            },
            "model_params": {
                "note_generation": {"temperature": 0.1, "max_tokens": 2000},
                "vision": {"temperature": 0.1, "max_tokens": 500, "confidence_threshold": "medium"},
            },
            "pipeline": {
                "stage1_skip_window_seconds": 60,
                "frame_window_clinic_ms": 3000,
                "frame_window_procedural_ms": 7000,
                "screen_capture_fps": 2,
                "video_capture_fps": 1,
            },
            "feature_flags": {
                "screen_capture_enabled": True,
                "note_versioning_enabled": True,
                "session_pause_resume_enabled": True,
                "per_session_provider_override": True,
            },
        }
        config = AppConfigSchema.model_validate(raw)
        assert config.providers.transcription == TranscriptionProviderKey.WHISPER
        assert config.feature_flags.screen_capture_enabled is True

    def test_defaults_applied(self):
        config = AppConfigSchema()
        assert config.providers.transcription == TranscriptionProviderKey.WHISPER
        assert config.pipeline.frame_window_clinic_ms == 3000

    def test_invalid_provider_key_rejected(self):
        with pytest.raises(ValidationError):
            AppConfigSchema.model_validate({
                "providers": {"transcription": "deepgram"},
            })

    def test_procedural_less_than_clinic_rejected(self):
        with pytest.raises(ValidationError):
            AppConfigSchema.model_validate({
                "pipeline": {
                    "frame_window_clinic_ms": 5000,
                    "frame_window_procedural_ms": 2000,
                },
            })

    def test_partial_update_preserves_defaults(self):
        config = AppConfigSchema.model_validate({
            "providers": {"note_generation": "gemini"},
        })
        assert config.providers.note_generation == NoteGenerationProviderKey.GEMINI
        assert config.providers.transcription == TranscriptionProviderKey.WHISPER  # default
        assert config.providers.vision == VisionProviderKey.OPENAI  # default


# ── #76 alerting thresholds ──────────────────────────────────────────────────


def test_alerting_absent_parses_to_defaults():
    """AC-1: hosted content predating the `alerting` block still parses,
    with defaults matching the MVP SLA targets + 24h purge window."""
    cfg = AppConfigSchema.model_validate(
        {"providers": {}, "model_params": {}, "pipeline": {}, "feature_flags": {}}
    )
    assert cfg.alerting.sla_stage1_ms == 30_000
    assert cfg.alerting.sla_stage2_ms == 300_000
    assert cfg.alerting.purge_gap_hours == 24


def test_alerting_block_overrides_and_bounds():
    """AC-2: an explicit block overrides; out-of-range fails validation."""
    cfg = AppConfigSchema.model_validate(
        {
            "providers": {},
            "model_params": {},
            "pipeline": {},
            "feature_flags": {},
            "alerting": {"sla_stage1_ms": 60_000, "purge_gap_hours": 48},
        }
    )
    assert cfg.alerting.sla_stage1_ms == 60_000
    assert cfg.alerting.sla_stage2_ms == 300_000  # untouched key keeps default
    assert cfg.alerting.purge_gap_hours == 48

    import pytest as _pytest

    with _pytest.raises(Exception):
        AppConfigSchema.model_validate(
            {
                "providers": {},
                "model_params": {},
                "pipeline": {},
                "feature_flags": {},
                "alerting": {"sla_stage1_ms": 1},  # below ge=1000
            }
        )


class TestModelVersionsConfig:
    """#437 — per-provider model-ID overrides (ships dark, all-None default)."""

    def test_defaults_all_none(self):
        mv = ModelVersionsConfig()
        assert mv.gemini is None
        assert mv.openai is None
        assert mv.anthropic is None

    def test_appconfig_default_block_is_all_none(self):
        # An AppConfig built without model_versions still gets the block,
        # all-None → providers fall back to their compiled-in _MODEL.
        config = AppConfigSchema()
        assert config.model_versions.gemini is None

    def test_doc_without_model_versions_validates(self):
        # Older hosted documents predate the key — must still validate.
        raw = {
            "providers": {"transcription": "whisper", "note_generation": "anthropic", "vision": "openai"},
            "model_params": {
                "note_generation": {"temperature": 0.1, "max_tokens": 2000},
                "vision": {"temperature": 0.1, "max_tokens": 500, "confidence_threshold": "medium"},
            },
            "pipeline": {"stage1_skip_window_seconds": 60, "frame_window_clinic_ms": 3000,
                         "frame_window_procedural_ms": 7000, "screen_capture_fps": 2, "video_capture_fps": 1},
            "feature_flags": {"screen_capture_enabled": True, "note_versioning_enabled": True,
                              "session_pause_resume_enabled": True, "per_session_provider_override": True},
        }
        config = AppConfigSchema.model_validate(raw)
        assert config.model_versions.gemini is None

    def test_override_round_trips(self):
        config = AppConfigSchema.model_validate({
            "providers": {"transcription": "whisper", "note_generation": "anthropic", "vision": "openai"},
            "model_params": {
                "note_generation": {"temperature": 0.1, "max_tokens": 2000},
                "vision": {"temperature": 0.1, "max_tokens": 1500, "confidence_threshold": "medium"},
            },
            "pipeline": {"stage1_skip_window_seconds": 60, "frame_window_clinic_ms": 3000,
                         "frame_window_procedural_ms": 7000, "screen_capture_fps": 2, "video_capture_fps": 1},
            "feature_flags": {"screen_capture_enabled": True, "note_versioning_enabled": True,
                              "session_pause_resume_enabled": True, "per_session_provider_override": True},
            "model_versions": {"gemini": "gemini-3.1-pro-preview"},
        })
        assert config.model_versions.gemini == "gemini-3.1-pro-preview"
        assert config.model_versions.openai is None


class TestVisionMaxTokensBounds:
    """#437 — vision max_tokens ceiling raised 4000 → 8000."""

    def test_default_is_1500(self):
        assert VisionModelParams().max_tokens == 1500

    def test_old_4000_still_allowed(self):
        assert VisionModelParams(max_tokens=4000).max_tokens == 4000

    def test_new_ceiling_8000_allowed(self):
        assert VisionModelParams(max_tokens=8000).max_tokens == 8000

    def test_above_ceiling_rejected(self):
        with pytest.raises(ValidationError):
            VisionModelParams(max_tokens=8001)

    def test_below_floor_rejected(self):
        with pytest.raises(ValidationError):
            VisionModelParams(max_tokens=50)

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
    # ── Clip cadence floor (#324) ──────────────────────────────────────
    # Interval, in seconds, at which iOS extracts at least one clip during
    # recording REGARDLESS of spoken triggers. 0 (the default) is off —
    # back-compatible with today's pilot, where clips are produced only at
    # keyword-trigger timestamps. When >0, iOS extracts ≥1 clip every N
    # seconds so a SILENT physical exam (a clinician examining without
    # narrating) still produces time-anchored visual evidence; the backend
    # captions those cadence clips even when the session has zero spoken
    # triggers. Cadence extraction is skip-if-trigger-covered on iOS — a
    # window already covered by a trigger clip does not also emit a cadence
    # clip, so the floor only fills silent gaps. dev runs at 30s. Bounds
    # 0..300 — 0 disables, 300s (5min) is a paranoia ceiling so a
    # misconfiguration can't flood S3 with sub-window clips. MUST stay in
    # lockstep with the AppConfig JSON-Schema validator
    # (infrastructure/appconfig.tf).
    clip_cadence_seconds: int = Field(default=0, ge=0, le=300)
    # ── Stage 1 entry guard (lane-backend/empty-transcript-guard) ─────
    # Minimum cumulative transcript character count below which Stage 1
    # is short-circuited with a STAGE1_SKIPPED_LOW_TRANSCRIPT audit
    # event. 20 characters is roughly "yeah, that's good." — anything
    # shorter is silence or button-mash noise. The provider is NEVER
    # called below this threshold; CLAUDE.md §"The Single Most
    # Important Constraint" forbids generative calls with no source
    # material. Bounds 0..1000 — 0 disables the low-transcript branch
    # (the empty/missing branch still fires), 1000 is a paranoia
    # ceiling for eval-team experiments.
    min_transcript_char_threshold: int = Field(default=20, ge=0, le=1000)
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
    # ── Windowed media retention (#338) ────────────────────────────────
    # How long raw session media (audio + masked clips/frames) is retained
    # in S3, expressed in days. Keep-full-window model: media stays
    # available for the full window and is removed ONLY by the S3 lifecycle
    # TTL (the max-window backstop) or by an on-demand Law 25 erasure —
    # final-note approval does NOT purge. Read ONLY when
    # `feature_flags.media_review_retention_enabled` is True; when that flag
    # is OFF nothing consults this value (the S3 lifecycle TTL alone governs
    # retention). Seven days is enough for a clinician to come back and
    # replay the encounter audio during review without re-recording. Bounds
    # 1..30 MUST match the AppConfig JSON-Schema validator another lane
    # adds — do not widen them here without widening that validator in
    # lockstep.
    media_review_retention_days: int = Field(default=7, ge=1, le=30)


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
    # ── Video-vision master gates (lane-backend/vision-evidence-feature-flags)
    # Two independent on/off master switches for the two video-vision
    # paths. They are NOT the same as `screen_capture_enabled` (which gates
    # the frame-by-frame *screen* OCR pipeline) — these gate the *patient*
    # video-vision paths. `resolve_evidence_mode` clamps the active
    # `VisualEvidenceMode` by these two flags (highest-precedence
    # resolution step). Defaults `True` so current behavior is preserved;
    # the operator flips clip=true/frame=false (or vice-versa) via
    # AppConfig to force a single path pilot-wide without a redeploy.
    #
    # Gemini native-video / clip-understanding path (providers.vision_clip).
    clip_video_interpretation_enabled: bool = True
    # Per-frame static-image vision path (providers.vision).
    frame_by_frame_video_enabled: bool = True
    # ── Post-pilot card visibility (lane-full/card-visibility-flags) ──────
    # Four downstream-of-Stage-1 cards (Orders, Coding & Billing, Patient
    # Summary, EMR Write-Back) ship in the iOS note-review surface but are
    # post-pilot scaffolding — their backends do not yet function. Hidden
    # by default for everyone; ADMIN flips per-card via POST
    # /admin/feature-flags. Defaults match the AppConfig hosted version
    # the operator pushes after deploy (all four False).
    orders_card_enabled: bool = False
    coding_card_enabled: bool = False
    patient_summary_card_enabled: bool = False
    emr_writeback_card_enabled: bool = False
    # ── Windowed media retention (#338) ───────────────────────────────────
    # Master gate for the windowed media-retention feature. Keep-full-window
    # model: when ON, raw session audio (and masked clips/frames) is retained
    # for the full `pipeline.media_review_retention_days` window and exposes
    # the audio-replay (and upcoming admin-download) surfaces so a clinician
    # can replay the encounter audio during review. The flag triggers NO
    # purge — media is removed only by the S3 lifecycle TTL (the max-window
    # backstop) or by an on-demand Law 25 erasure; final-note approval never
    # deletes it early. DEFAULT OFF — when OFF the replay/download surfaces
    # are not exposed (the audio-replay endpoint 403s) and the S3 lifecycle
    # TTL alone governs retention. PHI-sensitive, so it ships dark and the
    # operator flips it via POST /admin/feature-flags.
    media_review_retention_enabled: bool = False


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

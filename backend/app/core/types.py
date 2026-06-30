"""Shared Pydantic types used across all modules.

Modules never import from each other — shared types live here in core/.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# ── Transcript Types ───────────────────────────────────────────────────────

class TranscriptSegment(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: Optional[str] = None
    speaker_confidence: Optional[float] = None
    is_visual_trigger: bool = False
    trigger_type: Optional[str] = None


class Transcript(BaseModel):
    session_id: str
    provider_used: str
    segments: list[TranscriptSegment] = Field(default_factory=list)


# ── Template Types ─────────────────────────────────────────────────────────

class TemplateSection(BaseModel):
    id: str
    title: str
    required: bool = True
    visual_trigger_keywords: list[str] = Field(default_factory=list)
    description: str = ""
    # #63: True when this section can carry on-device visual measurements
    # (wound dimensions / ROM angles) as claims — e.g. wound_assessment
    # (plastic), physical_exam / functional_assessment (orthopedic / MSK).
    # The pipeline reads this to know a section may receive metric claims.
    # Defaults False so existing templates are unchanged.
    measurement_output_expected: bool = False


class Template(BaseModel):
    key: str
    display_name: str
    version: str = "1.0"
    sections: list[TemplateSection] = Field(default_factory=list)
    # Optional note-generation instructions carried by the template (tpl-01).
    # When set, this REPLACES the registry default note-gen system prompt for
    # notes produced with this template — slotted between a clinician's personal
    # override and an admin publication in `assemble_prompt`. None (or empty) =
    # the template shapes structure only. Validated against the descriptive-mode
    # gate (`validate_user_prompt`) whenever a custom template is written.
    system_prompt: Optional[str] = None


# ── Note Types ─────────────────────────────────────────────────────────────

class ClaimSource(BaseModel):
    """One additional grounding anchor for a claim (#552, GS-6).

    A descriptive claim cites a single source via ``source_id`` /
    ``source_quote`` on ``NoteClaim``. A SYNTHESIZED Assessment & Plan claim
    (Grounded Synthesis Mode) may rest on several findings — the extra anchors
    live in ``NoteClaim.additional_sources``. Each is a real source anchor, so
    synthesis stays fully traceable. Empty ``source_id`` is rejected, same as
    the primary anchor.
    """

    source_id: str = Field(..., min_length=1, description="Non-empty source anchor id")
    source_quote: str = ""


class NoteClaim(BaseModel):
    """A single factual claim in a note section.

    Every claim must be traceable to a source. `source_type` says where the
    text came from; `source_id` is the anchor (transcript segment id, frame
    id, screen frame id, or — for physician-authored claims — a stable
    sentinel like `pedit_{section_id}`). Empty `source_id` is rejected so
    Stage 1 / Stage 2 outputs can't ship an unanchored claim.

    Physician edits preserve provenance: a claim originating from a
    transcript segment keeps its `source_type="transcript"` and `source_id`,
    but `physician_edited` flips True and `original_text` captures the
    pre-edit text. Brand-new physician-authored claims use
    `source_type="physician_edit"` directly.
    """

    id: str
    text: str
    source_type: Literal[
        "transcript", "visual", "screen", "physician_edit", "measurement"
    ]
    source_id: str = Field(..., min_length=1, description="Non-empty source anchor id")
    source_quote: str = ""
    # Extra grounding anchors for a SYNTHESIZED claim (#552, GS-6). Empty for
    # every descriptive claim (back-compat); populated only when a grounded
    # A&P statement rests on several findings. The primary source_id above
    # stays required, so a claim is never anchorless.
    additional_sources: list[ClaimSource] = Field(default_factory=list)
    physician_edited: bool = False
    original_text: Optional[str] = None

    @property
    def all_source_ids(self) -> list[str]:
        """Primary anchor + every additional anchor, in order. Lets the
        grounding gates (critique, traceability metrics) treat a synthesized
        multi-source claim uniformly."""
        return [self.source_id, *(s.source_id for s in self.additional_sources)]


class NoteSection(BaseModel):
    id: str
    title: str = ""
    status: Literal["populated", "pending_video", "not_captured", "processing_failed"] = "not_captured"
    claims: list[NoteClaim] = Field(default_factory=list)


class MeasurementCitation(BaseModel):
    """An on-device visual measurement (wound dimension or ROM angle) that a
    physician confirmed before it entered the note (#63).

    Computed 100% on the iPhone (ARKit world-tracking + LiDAR depth, or an
    AR goniometer overlay); the backend only ever receives this structured
    record + a masked thumbnail — never raw frames. Carried into the note as
    a NoteClaim with ``source_type="measurement"`` / ``source_id=measurement_id``.

    Descriptive-mode + SaMD posture (CLAUDE.md §descriptive; design §6):
    every value is reported as "approximately" with its ``method`` +
    ``confidence``, and ``certified_measurement`` is ALWAYS False — the
    "approximate, not a certified measurement" disclaimer is structural, not
    cosmetic. No trends, no interpretation, no diagnosis.
    """

    measurement_id: str = Field(..., min_length=1)
    session_id: str
    frame_id: Optional[str] = None
    kind: Literal["wound_length", "wound_width", "wound_area", "rom_angle"]
    value: float = Field(..., ge=0)
    unit: Literal["mm", "cm2", "deg"]
    method: Literal[
        "arkit_lidar",
        "arkit_world",
        "fiducial_homography",
        "vision_pose_3d",
        "ar_goniometer",
    ]
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str = ""
    # How metric scale was recovered, e.g. "lidar_depth" / "world_tracking" /
    # "fiducial". Drives the confidence story; never PHI.
    scale_source: Optional[str] = None
    masking_status: Literal["confirmed", "failed", "not_applicable"] = "confirmed"
    physician_confirmed: bool = False
    provider_used: str = "on_device"
    model_version: str = "meas-1.0"
    # ALWAYS False — Aurion is a documentation aid, not a certified measuring
    # device (design §6). Typed as Literal[False] so it is structurally
    # impossible to ship a "certified" measurement.
    certified_measurement: Literal[False] = False

    @model_validator(mode="after")
    def _kind_unit_consistent(self) -> "MeasurementCitation":
        expected = {
            "wound_length": "mm",
            "wound_width": "mm",
            "wound_area": "cm2",
            "rom_angle": "deg",
        }[self.kind]
        if self.unit != expected:
            raise ValueError(
                f"unit '{self.unit}' invalid for kind '{self.kind}' "
                f"(expected '{expected}')"
            )
        return self


class PriorContextUsedSummary(BaseModel):
    """Slim count-only summary of how much prior-encounter context was
    fed into the Stage 1 LLM call for this note (#61, full slice).

    Attached to ``Note.prior_context_used`` after a Stage 1 generation
    that consumed prior context. Carries NO PHI: the integer count of
    encounters the model actually saw and the calendar date of the
    most recent prior visit (or null when no prior was found). The
    iOS badge and web chip read ``encounters_referenced > 0`` to
    decide whether to show the "Context-aware" affordance. Neither
    surface ever sees the prior session ids or any clinical content
    through this attribute — they re-fetch the rail via the existing
    ``/me/patients/{identifier}/sessions`` endpoint when the physician
    taps through.
    """

    encounters_referenced: int = Field(..., ge=0)
    # ISO-8601 calendar date as a string so the wire serialization is
    # deterministic across iOS / web clients without timezone
    # surprises. ``None`` when the lookup found zero prior encounters.
    last_encounter_date: Optional[str] = None


class Note(BaseModel):
    session_id: str
    stage: int
    version: int = 1
    provider_used: str
    specialty: str
    completeness_score: float = 0.0
    sections: list[NoteSection] = Field(default_factory=list)
    # ``prior_context_used`` is populated by the Stage 1 service when
    # the session's identifier matched at least one prior encounter
    # for this clinician. ``None`` when no prior context was loaded
    # (no identifier, lookup skipped, etc.) — distinct from
    # ``{encounters_referenced: 0, ...}`` which means "we looked but
    # found nothing". Older Stage 1 payloads pre-#61 decode unchanged
    # (defaults to None). NEVER carries PHI.
    prior_context_used: Optional[PriorContextUsedSummary] = None

    def get_section(self, section_id: str) -> Optional[NoteSection]:
        for s in self.sections:
            if s.id == section_id:
                return s
        return None


# ── Frame / Vision Types ──────────────────────────────────────────────────

class MaskedFrame(BaseModel):
    frame_id: str
    session_id: str
    timestamp_ms: int
    s3_key: str
    masking_confirmed: bool = False


# ── Clip Evidence ─────────────────────────────────────────────────────────
#
# Dual-mode visual evidence (see docs/plans/p1-1-clip-evidence-schema.md).
# `MaskedClip` is the sibling type to `MaskedFrame`: same masking-confirmed
# contract, additional per-clip masking metadata so the audit row can show
# how many frames the clip carried and how many faces were blurred. Audio
# is always stripped iOS-side (no audio track ever rides in a clip body),
# so the masked-clip contract is video-only.

class ClipMaskingMetadata(BaseModel):
    """Per-clip masking summary attached to every `clip_uploaded` and
    `clip_masked` audit row.

    The clip path masks every frame in the encoded window; the audit
    trail needs to show how many frames the clip carried so the
    compliance officer can reconcile "100% on-device masking" claims
    against the actual frame count, not just a boolean.

    Counts are non-negative integers; `frames_with_faces` and
    `faces_blurred` together prove that every detected face was blurred
    before the clip body crossed the wire (fail-closed gate in iOS
    `MaskingPipeline.maskClip`).
    """

    frames_total: int = Field(..., ge=0)
    frames_with_faces: int = Field(..., ge=0)
    faces_blurred: int = Field(..., ge=0)


class MaskedClip(BaseModel):
    """Server-side reference to a masked video clip uploaded by iOS.

    Mirrors `MaskedFrame` for the clip path. The clip body itself lives
    in S3 (KMS-encrypted, TTL-policy applied) at the key referenced by
    `s3_key`; `timestamp_ms` is the trigger anchor in transcript time;
    `duration_ms` is the encoded window length; `trigger_segment_id`
    points back at the transcript segment that fired the trigger.
    """

    s3_key: str
    timestamp_ms: int
    duration_ms: int = Field(..., ge=0)
    trigger_segment_id: str
    masking_metadata: ClipMaskingMetadata


class FrameCaption(BaseModel):
    frame_id: str
    session_id: str
    timestamp_ms: int
    audio_anchor_id: str
    provider_used: str
    visual_description: str
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str = ""
    conflict_flag: bool = False
    conflict_detail: Optional[str] = None
    integration_status: Literal["ENRICHES", "REPEATS", "CONFLICTS"]
    # ── Dual-mode visual evidence (P1-1) ──────────────────────────────
    # `FrameCaption` is the Liskov contract for BOTH frame and clip
    # captions — every provider returns this type from `caption_frame`
    # AND `caption_clip` so the merge / conflict-detection / Stage 2
    # loop stays evidence-kind-agnostic. `evidence_kind` defaults to
    # "frame" so today's call sites are byte-identical; `duration_ms`
    # is None for frames and set to the clip window for clips.
    evidence_kind: Literal["frame", "clip"] = "frame"
    duration_ms: Optional[int] = None
    # ── Lossy-fallback marker (P1-2) ───────────────────────────────────
    # Frame-only providers (OpenAI, Anthropic today) implement
    # `caption_clip` by extracting a midpoint still and routing through
    # `caption_frame`. The resulting citation is marked
    # `degraded_to_frame=True` so the iOS reviewer surfaces a "still
    # extracted from clip" badge — the physician sees they're not
    # getting full motion fidelity on that citation. Native-video
    # providers (Gemini) leave this False. Frame-path captions always
    # leave this False as well; the field is meaningful only when
    # `evidence_kind == "clip"`.
    degraded_to_frame: bool = False


# ── Screen Capture Types ──────────────────────────────────────────────────

class ScreenLabValue(BaseModel):
    name: str
    value: str
    unit: str = ""
    flag: str = "normal"


class ScreenExtractedData(BaseModel):
    type: str
    values: list[ScreenLabValue] = Field(default_factory=list)


class ScreenCaptureResult(BaseModel):
    frame_id: str
    session_id: str
    timestamp_ms: int
    screen_type: Literal["lab_result", "imaging_viewer", "emr", "other"]
    extracted_data: Optional[ScreenExtractedData] = None
    note_section_target: Optional[str] = None
    integration_status: Literal["injected", "skipped", "discarded"]


# ── Masking Proof ─────────────────────────────────────────────────────────

class MaskingProof(BaseModel):
    """Client-side masking proof attached to every frame upload.

    Mirrors the iOS `MaskingResult` struct. Only `masking_status == "success"`
    is acceptable — failed/skipped results MUST NOT reach the backend because
    iOS fail-closes the upload path.
    """

    frame_type: Literal["video", "screen"] = Field(..., description="'video' or 'screen'")
    masking_status: Literal["success"] = Field(..., description="Must be 'success'")
    faces_detected: int = Field(..., ge=0)
    phi_regions_redacted: int = Field(..., ge=0)


# ── Encounter Types ───────────────────────────────────────────────────────


class EncounterType(str, Enum):
    DOCTOR_PATIENT = "doctor_patient"
    DOCTOR_PATIENT_ALLIED = "doctor_patient_allied"
    DOCTOR_PATIENT_TRANSITORY = "doctor_patient_transitory"


class ParticipantRole(str, Enum):
    PHYSICIAN = "physician"
    NURSE = "nurse"
    PHYSICIAN_ASSISTANT = "pa"
    RESIDENT = "resident"
    FELLOW = "fellow"
    MEDICAL_STUDENT = "medical_student"


class SessionParticipant(BaseModel):
    name: str
    role: ParticipantRole
    is_persistent: bool = False


# ── Session Types ─────────────────────────────────────────────────────────

class SessionState(str, Enum):
    IDLE = "IDLE"
    CONSENT_PENDING = "CONSENT_PENDING"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"
    PROCESSING_STAGE1 = "PROCESSING_STAGE1"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    PROCESSING_STAGE2 = "PROCESSING_STAGE2"
    REVIEW_COMPLETE = "REVIEW_COMPLETE"
    EXPORTED = "EXPORTED"
    PURGED = "PURGED"
    # Stage 1 entry guard (lane-backend/empty-transcript-guard): set when
    # the transcript is missing, has zero segments, or carries less than
    # the AppConfig `pipeline.min_transcript_char_threshold` of usable
    # text. The provider is NEVER called in this branch — the only honest
    # documentation when there's no source material is "no audio
    # transcribed". The session is dead at this point; the iOS client
    # surfaces "re-record" and the session is discarded via
    # ``SESSION_DISCARDED``.
    STAGE1_FAILED_NO_AUDIO = "STAGE1_FAILED_NO_AUDIO"
    # Generic Stage 1 failure: transcription succeeded but the note-generation
    # provider call itself failed (parse error, rate limit, timeout, provider
    # outage) — distinct from STAGE1_FAILED_NO_AUDIO (empty transcript, provider
    # never called). Terminal, like NO_AUDIO. Before this state existed the
    # generic-failure path left the session in PROCESSING_STAGE1 forever, so a
    # provider hiccup stranded the session as perpetually "processing" with no
    # recovery (the iOS in-memory Retry only works while the app stays open).
    STAGE1_FAILED = "STAGE1_FAILED"


class UserRole(str, Enum):
    CLINICIAN = "CLINICIAN"
    EVAL_TEAM = "EVAL_TEAM"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    ADMIN = "ADMIN"
    # Elevatable super-user (#578): curates the template Library + publishes
    # prompts, but is NOT granted infra/security/regulatory surfaces (Feature
    # Flags, AI Providers, Config, Users, PHI, Audit). require_role is an
    # OR-set with no hierarchy, so this is added explicitly only where elevated.
    CLINICAL_ADMIN = "CLINICAL_ADMIN"


class PublicationScope(str, Enum):
    """Rollout scope for a Prompt Studio publication (PROMPT-STUDIO / PS-01).

    A published prompt version is made live for a cohort, narrowest first:
      * ``SELF`` — only the publishing admin's own sessions (test-in-prod).
      * ``ROLE`` — every user holding the publication's ``target_role``.
      * ``ALL``  — every clinician; the global default moves underneath
        anyone who has not saved a personal override.

    Resolution (ps-02) picks the most specific active publication for a
    given user. Stored as a plain ``VARCHAR`` column, never a Postgres enum,
    so adding a future scope stays a code change rather than a schema
    migration.
    """

    SELF = "SELF"
    ROLE = "ROLE"
    ALL = "ALL"


# ── Provider Error ────────────────────────────────────────────────────────

class ProviderError(Exception):
    """Typed error for provider failures. Never propagate raw API exceptions."""

    def __init__(self, provider: str, message: str, original: Optional[Exception] = None):
        self.provider = provider
        self.original = original
        super().__init__(f"[{provider}] {message}")

"""Shared Pydantic types used across all modules.

Modules never import from each other — shared types live here in core/.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

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


class Template(BaseModel):
    key: str
    display_name: str
    version: str = "1.0"
    sections: list[TemplateSection] = Field(default_factory=list)


# ── Note Types ─────────────────────────────────────────────────────────────

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
    source_type: Literal["transcript", "visual", "screen", "physician_edit"]
    source_id: str = Field(..., min_length=1, description="Non-empty source anchor id")
    source_quote: str = ""
    physician_edited: bool = False
    original_text: Optional[str] = None


class NoteSection(BaseModel):
    id: str
    title: str = ""
    status: Literal["populated", "pending_video", "not_captured", "processing_failed"] = "not_captured"
    claims: list[NoteClaim] = Field(default_factory=list)


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


class UserRole(str, Enum):
    CLINICIAN = "CLINICIAN"
    EVAL_TEAM = "EVAL_TEAM"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    ADMIN = "ADMIN"


# ── Provider Error ────────────────────────────────────────────────────────

class ProviderError(Exception):
    """Typed error for provider failures. Never propagate raw API exceptions."""

    def __init__(self, provider: str, message: str, original: Optional[Exception] = None):
        self.provider = provider
        self.original = original
        super().__init__(f"[{provider}] {message}")

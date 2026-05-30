"""SQLAlchemy ORM models for PostgreSQL tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.types import SessionState, UserRole


class UserModel(Base):
    """Aurion user account — clinicians, admins, eval, compliance.

    Self-registration via /auth/register defaults to CLINICIAN. Higher
    privilege roles (ADMIN, COMPLIANCE_OFFICER, EVAL_TEAM) are provisioned
    out-of-band by an operator updating the role column directly.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.CLINICIAN,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    voice_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specialty: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[SessionState] = mapped_column(
        Enum(SessionState, name="session_state"),
        nullable=False,
        default=SessionState.IDLE,
    )
    consultation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    encounter_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    encounter_type: Mapped[str] = mapped_column(String(50), nullable=False, default="doctor_patient")
    participants_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `multimodal` (default), `audio_only`, or `smart_dictation`. Chosen at
    # session creation on the iOS context sheet — drives capture-screen UI
    # today; the vision pipeline could short-circuit on non-multimodal modes
    # in a follow-up if we want to skip Stage 2 entirely for those.
    capture_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="multimodal"
    )
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PhysicianProfileModel(Base):
    """Physician preferences and practice configuration.

    Auto-created on first profile fetch. Stores preferred templates,
    practice type, consultation types, and output language preference.
    """

    __tablename__ = "physician_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    practice_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    primary_specialty: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    preferred_templates: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    consultation_types: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    allied_health_team: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    # Recording preferences set during onboarding's profile setup. These are
    # UX controls — `auto_upload` decides whether a finished encounter pushes
    # straight to Stage 1 or waits for an explicit confirm; `retention_days`
    # caps how long the device keeps the structured note locally before the
    # cleanup module purges; `consent_reprompt` gates the consent overlay
    # cadence (every session / daily / weekly).
    auto_upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    consent_reprompt: Mapped[str] = mapped_column(
        String(20), nullable=False, default="every_session"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TranscriptModel(Base):
    """Persisted transcript for a session.

    The Stage 2 vision pipeline needs access to trigger-flagged transcript
    segments after /transcription/{id} returns; storing the transcript as
    JSON on this row keeps the pipeline self-contained without requiring
    the client to resend it. One row per session — re-uploads overwrite.
    """

    __tablename__ = "transcripts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    provider_used: Mapped[str] = mapped_column(String(50), nullable=False)
    transcript_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class NoteVersionModel(Base):
    __tablename__ = "note_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_used: Mapped[str] = mapped_column(String(50), nullable=False)
    specialty: Mapped[str] = mapped_column(String(50), nullable=False)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized note
    is_approved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class CustomTemplateModel(Base):
    """User-owned specialty templates.

    Infrastructure for community templates — no UI yet. Templates follow
    the same JSON structure as the built-in file-based templates.
    """

    __tablename__ = "custom_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON template definition
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PilotMetricsModel(Base):
    """Passive pilot behaviour metrics -- collected per session, no PHI.

    Used post-pilot to decide if/where to fine-tune models. Access
    restricted to Eval Team and CTO. Retained for ML engineer analysis.
    """

    __tablename__ = "pilot_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    specialty: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # % required sections populated (target >= 90%)
    template_section_completeness: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # % claims with valid source_id (target >= 95%)
    citation_traceability_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # JSON-encoded dict of per-section physician edit rates
    physician_edit_rate_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # % frame citations classified CONFLICTS
    conflict_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # % frames discarded due to low confidence
    low_confidence_frame_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    # record_stop -> stage1_delivered (ms)
    stage1_latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # stage1_approved -> full_note_delivered (ms)
    stage2_latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # True when all 7 metrics above were logged successfully
    session_completeness: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class Stage2JobModel(Base):
    """Tracks async Stage 2 visual enrichment jobs.

    Created when /approve-stage1 fires; transitions pending → running →
    completed/failed as the background task progresses. Persisting state
    here lets iOS poll/recover after backgrounding without trusting an
    in-memory queue, and lets the dashboard show "Stage 2 in progress"
    tiles across the session list.
    """

    __tablename__ = "stage2_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # pending → running → completed|failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Resulting note version after vision merge — null until completion.
    new_note_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frames_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EvalScoreModel(Base):
    """Eval team quality scores submitted per session.

    One row per session — re-scoring overwrites in place (the audit log
    keeps the history). The session_id is the primary key because a
    session can only have one canonical score at a time; if the eval
    workflow ever grows multi-reviewer support, this becomes a
    (session_id, reviewer_id) composite and the model is updated then.
    """

    __tablename__ = "eval_scores"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    transcript_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    citation_correctness: Mapped[float] = mapped_column(Float, nullable=False)
    descriptive_mode_compliance: Mapped[float] = mapped_column(Float, nullable=False)
    overall: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scored_by: Mapped[str] = mapped_column(String(255), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Spec-aligned scoring (added v2, migration 0004). Nullable so
    # legacy slider-only scores keep validating and the legacy
    # frontend keeps submitting without these fields.
    descriptive_mode_pass: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    soap_section_scores: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    hallucination_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discrepancies: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)


class EvalAssignmentModel(Base):
    """Per-session eval-team assignment.

    One row per (session_id) — re-assigning overwrites in place (the audit
    log preserves history). Setting completed_at marks the assignment as
    finished — this happens when the assignee submits a score.
    """

    __tablename__ = "eval_assignments"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    assignee_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    assignee_email: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assigned_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProviderOverrideModel(Base):
    """Global runtime AI-provider override.

    Lets an ADMIN/COMPLIANCE_OFFICER pin the active provider for a given
    provider type at runtime (no redeploy, no new IAM grant). One row per
    provider type — the registry consults an in-memory cache that a
    background poller refreshes from this table every ~10s, so the
    override layer sits between the per-call override and AppConfig.

    The audit log preserves the full history; this table holds only the
    current effective override (upsert in place, delete to clear).
    """

    __tablename__ = "provider_overrides"

    # "transcription" | "note_generation" | "vision"
    provider_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider_value: Mapped[str] = mapped_column(String(32), nullable=False)
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AlertModel(Base):
    """Operational alert — surfaced when a clinical-pipeline trigger fires
    (a Stage failure, a masking issue, an SLA breach, etc.).

    Lives in Postgres alongside ``users`` and ``sessions`` rather than in
    the audit log because alerts are *operational* signals consumed by
    ADMIN and COMPLIANCE_OFFICER; the audit log remains the canonical,
    append-only clinical trail. An alert is an out-of-band notification
    of an event already recorded in the audit log (see issue #76).

    Best-effort publish at the trigger site keeps the audited code path
    independent of alert-DB availability.
    """

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # e.g. "stage1_failed", "stage2_failed", "transcription_failed",
    # "masking_failed", "sla_breach_stage1". Mirrors AuditEventType when
    # the trigger is an audit event; freeform when synthesised (SLA).
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "info" | "warning" | "critical" — mirrors AlertSeverity enum.
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # "transcription_service" | "vision_service" | "scheduler" | etc.
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # Short human-readable summary. Never carries PHI.
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured context (session_id, provider, retry_count, etc.).
    alert_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # Set by future PATCH /admin/alerts/{id}/acknowledge — null while open.
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class TemplateOverrideModel(Base):
    """Admin-managed override for a specialty template (issue #72).

    Layered on top of the disk-bundled JSON templates in
    ``app/modules/note_gen/templates/``. The CRUD endpoints persist here;
    runtime integration (in-memory cache + poller mirroring
    ``provider_overrides``) ships in a follow-up PR.

    One row per template key — upsert in place; delete to revert to the
    bundled default. The audit log preserves the full edit history.
    """

    __tablename__ = "template_overrides"

    # Matches Template.key (e.g. "musculoskeletal", "orthopedic_surgery").
    template_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Full Template JSON as serialised by Template.model_dump().
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )



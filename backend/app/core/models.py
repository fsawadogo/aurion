"""SQLAlchemy ORM models for PostgreSQL tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
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
    # ── AUTH-PIVOT-BACKEND — backend-issued JWT + TOTP MFA ─────────────────
    #
    # ``mfa_secret_encrypted`` is the KMS-encrypted TOTP base32 secret. The
    # raw secret is never persisted plaintext and never logged; the helper
    # in ``app.core.kms_encryption`` is the only call site. NULL until the
    # user enrolls; cleared back to NULL on admin-issued MFA reset.
    #
    # ``mfa_enrolled_at`` is the canonical "MFA on?" flag for the login
    # router. We keep both columns because the encrypted secret alone
    # would force a KMS round-trip every login just to know whether MFA
    # was set — the timestamp lets us short-circuit cheaply, then decrypt
    # only when verifying a code.
    #
    # ``failed_login_count`` + ``locked_until`` back the in-DB lockout
    # gate (5 failures → 15 minutes). Counter resets on successful login
    # so a returning user with a few stale failures doesn't stay near
    # the threshold forever. ``locked_until`` is a wall-clock timestamp:
    # once it passes, the next ``record_failure`` flips the counter
    # back to 1 (a fresh lockout window starts only after the next
    # streak), and a successful login zeroes both columns.
    #
    # ``last_password_changed_at`` is for the iOS forced-change UI in a
    # follow-up PR (we never enforce a hard rotation cadence here; the
    # column is the data anchor that lets a future policy do so without
    # a schema migration).
    # MFA enforcement (#397 / OV-5). When True, this user CANNOT finish a
    # password login until TOTP is enrolled (login returns
    # enroll_required). Default False everywhere → opt-in per user by an
    # ADMIN; the global "require for all" POLICY is the CTO's call, not
    # code. Ships dark: flipping nobody changes nothing.
    mfa_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Per-user prompt-testing capability (#590). When True, this user may
    # re-run note generation on their OWN uploaded encounters with a different
    # template/prompt (POST /sessions/{id}/regenerate-note). Admin-assignable,
    # orthogonal to role. Ships dark: default False → flipping nobody changes
    # nothing. Mirrors mfa_required's opt-in posture.
    prompt_testing_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Per-portal-MFA-card (#163): list[str] of bcrypt-hashed recovery
    # codes. Plaintext codes are returned to the user EXACTLY ONCE at
    # enrollment time and never re-fetchable. NULL until enrolled.
    mfa_recovery_codes_hashed: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Last successful TOTP verification — surfaced on the portal MFA
    # card so the clinician can confirm their authenticator is
    # actively in use. Updated by /auth/mfa/verify-login,
    # /me/mfa/verify-enroll, and DELETE /me/mfa (final verify).
    mfa_last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_password_changed_at: Mapped[datetime | None] = mapped_column(
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
    # Visit Type → Context → Template (#314 / B2). ``context_id`` is the
    # ``ctx_<8hex>`` id of the context the clinician chose on the iOS
    # context sheet at create time, sourced from their profile's
    # ``contexts_per_visit_type`` map (B1 / #313). NULL when no context
    # was chosen or the client predates the feature. ``template_key`` is
    # the SNAPSHOT of the built-in specialty template that context
    # resolved to — resolved + validated against ``list_available_templates``
    # once at create time so Stage 1 stays deterministic and auditable even
    # if the profile is edited mid-encounter. NULL means "use the session
    # ``specialty`` default", byte-for-byte the pre-#314 behaviour. Both
    # columns are non-PHI identifiers — never logged with patient context.
    context_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Custom-template binding snapshot (#318 / B3). When the chosen
    # context bound a custom ``template_ref`` (a ``custom_templates`` row
    # owned by the clinician) instead of a built-in ``template_key``, the
    # resolved-and-owned custom template id is snapshotted here at create
    # time so Stage 1 can load its content deterministically. Mutually
    # exclusive with ``template_key`` in practice — a context binds one or
    # the other. NULL means "no custom template" (use ``template_key`` or
    # the session ``specialty`` default). Plain UUID, not a DB-level FK:
    # the custom_templates row may be deleted after snapshot, in which
    # case Stage 1 degrades to the specialty default (never crashes).
    custom_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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
    # Session provenance (VID-01). NULL = live iOS capture (the only path
    # before this feature). "video_upload" = created by the web-portal
    # encounter-video import flow, which extracts audio/frames server-side
    # rather than receiving them from a live device. Drives the "Uploaded"
    # badge in the portal session lists and lets compliance segment
    # imported sessions. Additive + nullable so every existing row stays
    # valid as a live session.
    import_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PHI — KMS-envelope-encrypted patient identifier (MRN hash, EMR
    # encounter ID, etc.). Stored as ciphertext + IV; reading the row alone
    # never yields plaintext. Decryption goes through
    # app.core.kms_encryption.decrypt_str. Forward-compatible with FHIR
    # DocumentReference.identifier for the future EMR write-back path (#57).
    # Never logged, never returned to non-owner / non-admin roles.
    external_reference_id_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    # Deterministic HMAC-SHA256 of the same identifier, used for indexed
    # lookups (#61, full slice). 32 raw bytes; NULL when no identifier is
    # set on the row. The hash is one-way (HMAC; even with the column
    # leaked an attacker can't reverse it without the key), and is the
    # WHERE-clause anchor for `GET /me/patients/{identifier}/sessions`
    # and `get_prior_context`. Kept in sync with the encrypted column on
    # every PATCH /sessions/{id}/identifier. See
    # `app/core/identifier_hash.py` for the hashing rule.
    external_reference_id_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, index=True
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
    # Visit Type → Context → Template map (#313 / B1). JSON object stored
    # as text (same convention as ``consultation_types`` above), keyed by
    # visit-type key (a canonical default OR a custom consultation-type
    # label) → ordered list of context objects:
    #   {"new_patient": [{"id": "ctx_7f3a9c21", "label": "LL",
    #                     "template_key": "orthopedic_surgery",
    #                     "template_ref": null}, ...]}
    # ``template_key`` references a built-in specialty template; in phase 1
    # ``template_ref`` (custom-template pointer) is always null. Labels are
    # user-authored and gated through the same PHI format checks as
    # consultation types; the validator lives in app/api/v1/profile.py.
    contexts_per_visit_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    allied_health_team: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    # Portal/iOS chrome theme — distinct from output_language above
    # (which controls note generation). "system" follows the OS
    # setting; "light" / "dark" force one mode regardless.
    ui_theme: Mapped[str] = mapped_column(
        String(16), nullable=False, default="system"
    )
    # Physician accent color (#418 / OV-7) — personalization primitive.
    # A curated palette key (gold/teal/indigo/rose/slate), NOT free-form
    # hex, so the visual layer maps each to a pre-validated AA-contrast
    # token. "gold" = today's brand default → no visible change until the
    # picker + token wiring ship (the reviewed frontend slice).
    accent_color: Mapped[str] = mapped_column(
        String(16), nullable=False, default="gold"
    )
    # Portal/iOS chrome language. Orthogonal to output_language:
    # physicians may dictate in English and read the chrome in
    # French (or vice versa). "en" / "fr" today; IETF tags like
    # "fr-CA" forward-compatible.
    ui_language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en"
    )
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


class MeasurementCitationModel(Base):
    """Persisted on-device visual measurement (#63) — wound L/W + ROM.

    The backend only ever stores the structured, physician-confirmed
    citation (numbers + provenance) + (later) a masked thumbnail — never
    raw frames. Derived PHI (design §6.2): same KMS/retention/erasure rules
    as notes, so it's a session child row hard-deleted with the session
    (``_SESSION_CHILD_MODELS``). ``certified_measurement`` is always False
    (the disclaimer is structural). Mirrors ``MeasurementCitation`` in
    core/types.py.
    """

    __tablename__ = "measurement_citations"
    # iOS mints measurement_id per session (meas_001…); unique per session so
    # a re-POST is idempotent rather than a duplicate row.
    __table_args__ = (
        UniqueConstraint(
            "session_id", "measurement_id", name="uq_measurement_session_mid"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    measurement_id: Mapped[str] = mapped_column(String(64), nullable=False)
    frame_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(8), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scale_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    masking_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="confirmed"
    )
    physician_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    provider_used: Mapped[str] = mapped_column(
        String(32), nullable=False, default="on_device"
    )
    model_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="meas-1.0"
    )
    certified_measurement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
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
    # One custom template per (owner, runtime key). The service layer also
    # checks this in-app (friendly 409), but the DB constraint is the real
    # guarantee — without it the finalize/create paths could race two rows
    # with the same (owner_id, key), and a later scalar_one lookup 500s.
    __table_args__ = (
        UniqueConstraint("owner_id", "key", name="uq_custom_templates_owner_key"),
    )

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


class OrgVisitTypeTemplateModel(Base):
    """Org-wide default template per visit type — the visit-type → template map.

    The admin-set default that a clinician's own mapping (a visit type's
    ``is_default`` context, #577) overrides, which in turn a per-encounter
    context pin overrides. Consumed by ``resolve_context_template_key`` as the
    layer between the clinician default and the specialty default. One row per
    visit-type key; single-org for the pilot (no ``org_id``). ``template_key``
    (a built-in) XOR ``custom_template_id`` (a SHARED custom template) — the API
    enforces exactly one; the note pipeline re-validates both at resolve time so
    a stale pin degrades to the specialty default rather than erroring.
    """

    __tablename__ = "org_visit_type_templates"

    visit_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    template_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    custom_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
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

    # ── Clip-aware metrics (P1-FU-METRICS) ─────────────────────────────────
    #
    # All five are nullable, additive — old rows decode as null and the
    # admin endpoint already surfaces Optional fields. ``clip_count``,
    # ``clip_bytes_uploaded`` and ``clip_degraded_to_frame_count`` carry a
    # server-side default of 0 so downstream aggregations don't have to
    # COALESCE; the two mean/sum columns stay null when no clips were
    # processed so "no clips" never collapses to "0 ms" / "$0".
    #
    # Cost is stored as USD micros (1 USD = 1_000_000 micros) — integer
    # arithmetic preserves precision across Phase 2 aggregations; the
    # cost rate sheet lives in app/core/cost_rates.py.
    clip_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clip_bytes_uploaded: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    clip_avg_latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    clip_vision_spend_estimate_usd_micros: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    clip_degraded_to_frame_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
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


class VideoImportJobModel(Base):
    """Tracks async web-portal encounter-video import jobs (VID-01…).

    Created when an uploaded video is submitted for processing; transitions
    pending → running → completed/failed as the background job extracts
    audio (→ Stage 1), extracts + masks frames (→ Stage 2), and purges the
    raw video. Mirrors ``Stage2JobModel`` (which the web/iOS clients already
    poll) so the portal can poll/recover after navigation without trusting
    an in-memory queue. Ships inert — nothing writes rows until the
    video-import endpoints land behind ``feature_flags.video_import_enabled``.
    """

    __tablename__ = "video_import_jobs"

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
    # S3 key of the uploaded raw video (video-imports/{sid}/{uuid}.mp4).
    # For a single-clip import this is the only key. For a multi-clip import
    # it holds the FIRST clip (back-compat); the full ordered clip list lives
    # in `raw_video_s3_keys`.
    raw_video_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ordered list of clip S3 keys for a multi-clip import (sequential parts of
    # one encounter). NULL for legacy / single-clip jobs — processing falls
    # back to `[raw_video_s3_key]`. Concatenated in THIS order into one audio
    # timeline → one transcript → one note.
    raw_video_s3_keys: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Set once the raw video has been purged post-extraction — the audit
    # proof that no unmasked video lingers past processing.
    raw_video_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Frame pipeline counters (populated by the masking slice, VID-04).
    frames_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_masked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frames_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Whether the job auto-approves Stage 1 and runs Stage 2 (admin/eval
    # bulk runs) vs stops at AWAITING_REVIEW for human review (clinicians).
    auto_advance_stage2: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Resulting note version after Stage 2 merge — null until completion.
    new_note_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    # Provider attribution (#74 / OV-1, migration 0036). Denormalized from
    # the scored note at submit time so quality scores join to providers
    # without chasing the session→note_version chain at query time.
    # Nullable: pre-0036 rows are backfilled where a note exists;
    # model_name stays NULL until per-call usage records carry it.
    provider_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


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


class ComplianceReportModel(Base):
    """Persisted, hash-signed compliance report snapshot (issue #77).

    One row per generated report. ``content_bytes`` is the CSV payload
    stored inline at pilot scale — S3-backed storage is a follow-up
    when sizes grow. ``sha256`` is the hex digest of ``content_bytes``
    at generation time so a compliance officer can verify the
    downloaded file against the metadata row.
    """

    __tablename__ = "compliance_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # "audit" | "masking" | "retention" (foundation: only "audit" wired).
    report_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    content_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)


class ProviderUsageModel(Base):
    """Per-call AI-provider telemetry (issue #73).

    One row per call to the provider registry — written by trigger sites
    (note_gen/service.py, vision/service.py, transcription/service.py).
    Latency + success + fallback fields are captured today; token counts
    and ``cost_usd`` are nullable so this PR can land without waiting on
    the ``base.py`` provider‑interface refactor that surfaces ``usage``
    per call.

    Lives in Postgres next to ``alerts`` (operational telemetry) rather
    than ``pilot_metrics`` (per‑session clinical KPIs) so the dashboards
    can be queried independently.
    """

    __tablename__ = "provider_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # "transcription" | "note_generation" | "vision"
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # "openai" | "anthropic" | "gemini" | "whisper" | "assemblyai" | …
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Concrete model used for the call (e.g. "gpt-4o", "claude-sonnet-4-6").
    # Nullable until the base.py refactor surfaces it.
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "generate_note" | "caption_frame" | "transcribe"
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    # Per‑session attribution for the eval team; nullable for non‑session
    # contexts (health pings, future synthetic calls).
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
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


class TemplateAuthoringSessionModel(Base):
    """In-progress conversational template-builder sessions.

    Each row tracks one ChatGPT-style authoring conversation between a
    clinician and the template-authoring LLM. Resumable across devices —
    state lives here, not in browser storage.

    On finalize, the draft_template_json is validated against the Template
    Pydantic schema and inserted as a `custom_templates` row owned by the
    same clinician; this row stays for audit but flips to status=completed.
    """

    __tablename__ = "template_authoring_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # JSON-encoded list of {"role": "user" | "assistant", "content": "..."}
    # objects. Bounded by an application-level message limit (default 40)
    # so a runaway conversation doesn't bloat the row indefinitely.
    messages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Latest LLM-emitted draft, JSON-encoded. None until the assistant
    # produces a valid Template-schema candidate. Replaced (not appended)
    # each time the LLM emits a new draft.
    draft_template_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "abandoned", name="template_authoring_status"),
        nullable=False,
        default="active",
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


class PhysicianMacroModel(Base):
    """Per-physician text shortcut → expansion mapping.

    Typing the shortcut in a note edit field expands to the body.
    Owner-scoped via the (owner_id, shortcut) unique constraint —
    two physicians can independently use `/ros` to mean different
    things; one physician can't accidentally collide their own
    shortcuts.

    Body is treated as non-PHI (clinical phrases, not patient data)
    but is never logged regardless. Audit events capture create /
    update / delete without including the body text.
    """

    __tablename__ = "physician_macros"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    shortcut: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional specialty scope. Null = available everywhere this
    # physician records; non-null = only inside that specialty's notes.
    specialty: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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


class ScheduleEntryModel(Base):
    """A patient the clinician has queued onto their personal schedule.

    Owner-scoped like macros (every query filters on ``clinician_id``).
    Operational, not clinical: it holds who the clinician plans to see,
    an optional slot time, an optional short note, and a lifecycle
    status. It is NOT a calendar/booking system — ``scheduled_for`` is a
    single optional timestamp with no conflict detection or recurrence.

    PHI posture mirrors ``SessionModel``: the patient identifier is
    stored KMS-encrypted (``patient_identifier_encrypted``) plus a
    deterministic HMAC (``patient_identifier_hash``) for indexed lookup.
    The plaintext identifier never lands in a column, a log, or an audit
    row; it is decrypted only in the owning clinician's API response.
    ``note`` is PHI-adjacent free text — encrypted at rest via the RDS
    volume, never logged, never audited.
    """

    __tablename__ = "schedule_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # PHI — same KMS-encrypted + HMAC-hashed pair as SessionModel. Reading
    # the row alone never yields plaintext; decryption goes through
    # app.core.kms_encryption.decrypt_str.
    patient_identifier_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    patient_identifier_hash: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, index=True
    )
    # Lifecycle status. Stored as a plain string (like `specialty` on
    # macros) with service-layer validation of the allowed set + legal
    # transitions, rather than a native PG enum type — keeps the migration
    # additive and the value set easy to evolve.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled"
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class PatientSummaryModel(Base):
    """Plain-language after-visit summary derived from an approved note.

    One-to-many on session — physicians can regenerate or edit. The
    latest row (max `version` for the session) is what the UI shows.
    Ownership flows through `sessions.clinician_id`; this table does
    not duplicate it (single source of truth, avoids drift if a
    session is ever reassigned).

    Body is PHI (it references the encounter) — stored as plain text
    on the encrypted-at-rest RDS volume; no extra column-level
    encryption needed (would over-engineer the threat model for a
    physician-only read surface).
    """

    __tablename__ = "patient_summaries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    physician_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
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


class NoteOrderModel(Base):
    """Structured order extracted from an approved note.

    Each row is one orderable action (an MRI, a referral, a
    prescription, a lab) the physician dictated during the encounter.
    The LLM extracts these from the note's Plan / Imaging / Investigations
    sections; physician confirms each draft before it's eligible for
    outbound delivery (which is #57 territory).

    Ownership flows through `sessions.clinician_id` — this table doesn't
    duplicate it.

    `details` is type-specific JSONB and is PHI-adjacent (drug names,
    body parts, indications) — never logged, never in the audit row.
    """

    __tablename__ = "note_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        Enum("imaging", "lab", "referral", "prescription", name="note_order_kind"),
        nullable=False,
    )
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            "draft", "confirmed", "sent", "cancelled",
            name="note_order_status",
        ),
        nullable=False,
        default="draft",
    )
    # JSON array of claim IDs (`["c001","c003"]`) so the audit chain
    # back to the source note is queryable without re-running the LLM.
    source_claim_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    physician_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Drug catalog validation flag — populated at extraction time for
    # prescription rows only; NULL for imaging / lab / referral kinds
    # (those don't have a drug field). Three-state semantics same as
    # CodingSuggestionModel.code_validated: True = recognized,
    # False = checked-and-not-in-catalog, None = unvalidated.
    drug_validated: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    # Catalog version in effect when drug_validated was set. NULL
    # when the row predates this column OR the kind doesn't get
    # validated (imaging/lab/referral). Stored not re-derived — the
    # catalog evolves; this row's validation result must remain
    # explainable against the catalog state at extraction time.
    catalog_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
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


class CodingSuggestionModel(Base):
    """E/M, ICD-10, CPT suggestion for an approved session — #69.

    Strategic separate surface. Aurion's clinical note is descriptive
    only by policy; this table holds the inferential side (LLM mapping
    free-text findings to billing codes) on its OWN row, never written
    back into note sections. The portal renders these on a dedicated,
    clearly-labeled card; physician confirms / rejects / edits each
    row before it's eligible for EMR write-back (#57).

    Ownership flows through `sessions.clinician_id`. `description` and
    `justification` are PHI-adjacent free text — never logged, never
    in audit rows. The `code` itself is allowed in the audit log
    (it's the whole point of the trail).
    """

    __tablename__ = "coding_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    code_system: Mapped[str] = mapped_column(
        Enum("em", "icd10", "cpt", name="coding_system"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    source_claim_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="coding_confidence"),
        nullable=False,
        default="medium",
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "suggested", "confirmed", "rejected", "edited",
            name="coding_status",
        ),
        nullable=False,
        default="suggested",
    )
    physician_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Catalog-validation flag computed at extraction time. True means
    # the code was in our curated catalog; False means it actively
    # wasn't; None means the row predates the validation feature.
    # NEVER recomputed on read — the catalog evolves and we want the
    # audit story to reflect the catalog state at extraction time.
    code_validated: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    # Catalog version in effect when code_validated was set. NULL
    # for rows from before this column existed. Same audit-story
    # rationale as NoteOrderModel.catalog_version.
    catalog_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
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


class EmrWriteBackModel(Base):
    """Outbound delivery attempt of an approved note to an EMR — #57.

    One row per send attempt. Foundation supports the `stub` connector;
    real backends (Oscar, Epic SMART, generic FHIR endpoint) land in
    follow-up issues.

    `payload_fingerprint` is sha256 hex of the serialized payload — we
    don't store the payload itself (PHI-bound; EMR is the source of
    truth post-send). The fingerprint lets us detect duplicate sends
    of the same note without keeping the payload around.

    Ownership flows through `sessions.clinician_id`.
    """

    __tablename__ = "emr_write_backs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    connector: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            "queued", "sending", "sent", "failed",
            name="emr_write_back_status",
        ),
        nullable=False,
        default="queued",
    )
    external_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    payload_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
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


class LiveNotePreviewModel(Base):
    """Streaming draft note snapshot generated during recording — #64.

    NOT the canonical Stage 1 note. These are previews — the physician
    watches the note assemble while still in the room with the patient.
    The canonical pipeline at recording-stop runs the full Stage 1
    generation independently, ignoring any preview rows.

    Each row is one snapshot. We keep history rather than overwriting
    so the pilot can chart how the note evolved over the encounter.

    The sections JSON is PHI-bound (same as Stage 1 notes); never in
    logs or audit rows. Ownership flows through `sessions.clinician_id`.
    """

    __tablename__ = "live_note_previews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sections: Mapped[list] = mapped_column(JSONB, nullable=False)
    transcript_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    completeness_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    provider_used: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PromptOverrideModel(Base):
    """Per-physician REPLACEMENT user prompt for an AI system prompt.

    Phase B of AI Prompts Transparency (replacement semantics — CTO
    clarification). Each row pairs an ``owner_id`` (the clinician's
    user UUID) with a ``prompt_id`` (the registry dict key in
    ``app.modules.prompts.registry``) and stores the physician's full
    standalone system prompt in ``user_prompt_text``.

    Selection (not assembly): when this row exists,
    ``app.modules.prompts.assembly.assemble_prompt`` returns
    ``user_prompt_text`` **alone**. The registry's base prompt is the
    fallback used only when no row exists for ``(owner_id,
    prompt_id)``. There is no concatenation — the saved text fully
    replaces the system default for this physician's sessions.

    Why ``PromptOverrideModel`` (not ``UserPromptModel``)? The table
    name ``prompt_overrides`` and the model class name shipped in PR
    #227 v1; renaming both costs a destructive migration without buying
    a behavioural change. The column name (``user_prompt_text``) is
    what carries the corrected mental model — that is what the
    validator, the API, and the LLM all see.

    Ownership is strict: Marie's saved prompt never bleeds into
    Perry's assembled prompt, and vice versa. The ``UNIQUE (owner_id,
    prompt_id)`` constraint guarantees one row per (physician,
    prompt). Re-saving upserts.

    User prompt text is NOT PHI but is sensitive (it's the
    physician's personal phrasing). It's never logged, never echoed
    in audit rows — only the ``user_prompt_length`` int makes the
    audit trail.
    """

    __tablename__ = "prompt_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Matches the PROMPTS dict key in ``app.modules.prompts.registry``.
    # Not a foreign key — the registry lives in code, not the DB; new
    # prompts ship with the next deploy. The 64-char cap matches the
    # convention used by PhysicianMacroModel.shortcut for the same
    # reason (identifiers, not free text).
    prompt_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # The physician's full standalone system prompt that REPLACES the
    # registry default for their own sessions. Validator-enforced cap
    # is 5000 chars (see ``app.modules.prompts.safety``); no DB CHECK
    # because length policy may evolve faster than schema.
    user_prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
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


class StudioPromptModel(Base):
    """An admin-authored, versioned candidate prompt for one AI job
    (PROMPT-STUDIO / PS-01).

    Distinct from ``PromptOverrideModel``: that table holds a *clinician's*
    personal replacement for their own sessions. This one holds an *admin's*
    named candidate for a pipeline job (``job_id`` = a key in
    ``app.modules.prompts.registry.PROMPTS``) that — once published (ps-05) —
    becomes the global default underneath every clinician who has not saved a
    personal override. A job can carry several candidates; their text lives in
    the append-only ``StudioPromptVersionModel`` children.

    ``job_id`` is NOT a foreign key, for the same reason as
    ``PromptOverrideModel.prompt_id``: the registry lives in code, not the DB.
    ``created_by`` is nullable / ``SET NULL`` on user delete so a global prompt
    outlives the admin who authored it — it is org config, not personal config.
    """

    __tablename__ = "studio_prompts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Matches a PROMPTS dict key in ``app.modules.prompts.registry``.
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Soft-archive: hidden from the library but versions/publications stay
    # referenceable. NULL = active.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class StudioPromptVersionModel(Base):
    """One immutable version of a ``StudioPromptModel`` (PS-01).

    Append-only: every save in the Studio writes a new row with the next
    ``version_no`` for its parent; rows are never updated or deleted. The
    ``UNIQUE (studio_prompt_id, version_no)`` constraint keeps the version
    sequence monotonic and collision-free. ``text`` is the full standalone
    system prompt (validated structurally before insert by ps-03 via
    ``app.modules.prompts.safety.validate_user_prompt``); it is not PHI but is
    sensitive, so it never enters logs or audit rows — only its length does.
    """

    __tablename__ = "studio_prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    studio_prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("studio_prompts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "studio_prompt_id",
            "version_no",
            name="uq_studio_prompt_versions_prompt_version",
        ),
    )


class PromptPublicationModel(Base):
    """Append-only record that a ``StudioPromptVersionModel`` is (or was) live
    for a cohort of a job (PS-01; written by ps-05).

    Resolution (ps-02) reads the active publication — ``superseded_at IS
    NULL`` — for a clinician's job, picking the most specific scope: ``SELF``
    (``target_user_id``) over ``ROLE`` (``target_role``) over ``ALL``.
    Publishing a new version supersedes the prior active row for the same
    ``(job_id, scope, target)`` by stamping ``superseded_at`` rather than
    deleting it, so the full rollout history stays auditable.

    ``job_id`` is denormalized (also reachable via the version's parent) so the
    hot resolution lookup filters one indexed column without a join. ``scope``
    / ``target_role`` carry ``PublicationScope`` / ``UserRole`` values (see
    ``app.core.types``) as plain strings, keeping a new scope a code change,
    not a schema migration.
    """

    __tablename__ = "prompt_publications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("studio_prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # PublicationScope value: "SELF" | "ROLE" | "ALL".
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    # Set only when scope == "ROLE" — a UserRole value.
    target_role: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # Set only when scope == "SELF" — the publishing admin's user id. SET NULL
    # (not CASCADE) on user delete: this table is append-only / auditable, so a
    # deleted clinician's SELF publication is orphaned (no SELF match), never
    # erased from the rollout history.
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # NULL = active. Stamped (not deleted) when a later publication takes over
    # the same (job_id, scope, target).
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RefreshTokenModel(Base):
    """Refresh-token row for the backend-issued JWT pipeline (AUTH-PIVOT-BACKEND).

    The raw token (a 256-bit URL-safe base64 string) is returned to the
    client exactly once — in the body of the issuing /auth/login or
    /auth/refresh response. The DB stores only ``token_hash`` (SHA-256
    of the raw token). SHA-256 was chosen over bcrypt because the read
    path is a constant-time hash + indexed equality lookup, not a
    password verification — refresh tokens are random opaque secrets,
    not user-chosen, so brute-force resistance comes from entropy, not
    work factor.

    ``revoked_at`` is the canonical "is this token still good?" flag.
    Rotation on /auth/refresh sets the previous row's ``revoked_at``
    and writes a new row. Logout sets ``revoked_at`` on the row of the
    refresh token presented in the request. Password reset revokes
    every refresh token for the user. Lookups always filter on
    ``revoked_at IS NULL AND expires_at > now()``.

    ``issued_user_agent`` and ``issued_ip_hash`` are best-effort
    forensics signals so a compromise audit can correlate a leaked
    token to a device — never logged in plaintext, never PHI, never
    user-presented. ``issued_ip_hash`` is SHA-256 of the raw IP for
    the same one-way reason refresh tokens are stored hashed.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issued_user_agent: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    issued_ip_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    # Per-portal-sessions-card (#163): the three columns below back the
    # portal "Active sessions" view. ``device_hint`` is a derived UA
    # fingerprint (e.g. ``"Safari · macOS"``) at most 64 chars; never the
    # raw UA, never PHI. ``last_used_at`` is updated on every
    # /auth/refresh rotation so the card can sort by recency.
    # ``access_token_jti`` is the JTI of the most recently issued access
    # token for this refresh row — it lets /me/sessions flag
    # ``is_current=True`` on the row whose JTI matches the bearer token
    # of the caller.
    device_hint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_token_jti: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class PasswordResetTokenModel(Base):
    """Self-serve email-link password reset token (AUTH-PIVOT-BACKEND).

    Same one-way storage as ``RefreshTokenModel``: the raw token is
    URL-safe and goes into the reset link emailed to the user; the DB
    stores SHA-256. 24-hour TTL. Each row is single-use — verifying a
    token sets ``consumed_at`` so a replay of the same link 401s. The
    audit-trail invariant is reconstructible from the row regardless
    of whether the reset succeeded.

    The forgot-password endpoint always returns 204, even when the email
    doesn't map to a user, so the column ``user_id`` is FK-CASCADE'd
    from ``users.id`` because we never write a row at all for unknown
    emails — there's nothing to FK to.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

"""Typed catalog of audit event types.

Every immutable audit log entry written by Aurion carries an
``event_type`` string. Historically these were untyped literals
scattered through route handlers and service modules. This file
collects them into a single ``StrEnum`` so:

  * the compliance officer can read one file to inventory what we
    emit;
  * `grep AuditEventType.FOO` finds every emission of a given event;
  * typos become syntax errors instead of silently divergent rows in
    DynamoDB.

Wire-format invariant
---------------------
Every member's ``.value`` is the exact byte sequence already written
to DynamoDB. **Do not rename, retype-case, or otherwise change an
existing member's value.** Historical audit queries (compliance
reports, pilot metrics dashboards) join on these strings; a rename
silently breaks them. To add a new event type, append a new member.
To deprecate one, leave it in place and stop emitting it.

`test_audit_event_type_values_locked` in
``tests/unit/test_audit_events.py`` asserts the full
member → value map; any accidental rename trips it.
"""

from __future__ import annotations

from enum import StrEnum


class AuditEventType(StrEnum):
    """Canonical catalog of audit event types written by Aurion."""

    # ── Lifecycle (session state transitions) ────────────────────────────
    SESSION_CREATED = "session_created"
    CONSENT_CONFIRMED = "consent_confirmed"
    RECORDING_STARTED = "recording_started"
    SESSION_PAUSED = "session_paused"
    STAGE1_STARTED = "stage1_started"
    STAGE1_DELIVERED = "stage1_delivered"
    STAGE2_STARTED = "stage2_started"
    FULL_NOTE_DELIVERED = "full_note_delivered"
    NOTE_EXPORTED = "note_exported"
    SESSION_PURGED = "session_purged"

    # ── Notes / review ───────────────────────────────────────────────────
    STAGE1_APPROVED = "stage1_approved"
    STAGE1_FAILED = "stage1_failed"
    STAGE2_SKIPPED = "stage2_skipped"
    STAGE2_COMPLETE = "stage2_complete"
    STAGE2_FAILED = "stage2_failed"
    NOTE_VERSION_CREATED = "note_version_created"
    TEMPLATE_CHANGED = "template_changed"
    CONFLICT_RESOLVED = "conflict_resolved"

    # ── Frames / masking ─────────────────────────────────────────────────
    FRAME_UPLOADED = "frame_uploaded"
    SCREEN_FRAME_PROCESSED = "screen_frame_processed"
    MASKING_CONFIRMED = "masking_confirmed"

    # ── Transcription ────────────────────────────────────────────────────
    TRANSCRIPTION_COMPLETE = "transcription_complete"
    TRANSCRIPTION_FAILED = "transcription_failed"
    S3_UPLOAD_FAILED = "s3_upload_failed"
    PHI_AUDIT_COMPLETE = "phi_audit_complete"
    SPEAKER_TAGS_APPLIED = "speaker_tags_applied"

    # ── Vision (Stage 2) ─────────────────────────────────────────────────
    VISION_FRAME_FAILED = "vision_frame_failed"
    PROVIDER_FALLBACK = "provider_fallback"

    # ── Cleanup pipeline ─────────────────────────────────────────────────
    AUDIO_PURGED = "audio_purged"
    FRAMES_PURGED = "frames_purged"
    EVAL_FRAMES_MIGRATED = "eval_frames_migrated"
    CLEANUP_PARTIAL_FAILURE = "cleanup_partial_failure"

    # ── Privacy / account ────────────────────────────────────────────────
    BIOMETRIC_CONSENT_CONFIRMED = "biometric_consent_confirmed"
    VOICE_ENROLLMENT_COMPLETE = "voice_enrollment_complete"
    VOICE_ENROLLMENT_DELETED = "voice_enrollment_deleted"
    ACCOUNT_DELETED = "account_deleted"

    # ── Admin ────────────────────────────────────────────────────────────
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    EVAL_SCORE_SUBMITTED = "eval_score_submitted"

    # ── System / config ──────────────────────────────────────────────────
    CONFIG_CHANGED = "config_changed"
    PROVIDER_CHANGED = "provider_changed"

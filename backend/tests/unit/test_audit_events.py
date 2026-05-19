"""Regression guard for ``AuditEventType`` (Q-01).

The enum's job is to be a typed catalog of audit event strings. The
compliance invariant is that every member's ``.value`` matches the
exact byte sequence already written to DynamoDB. A rename — even a
case change — would silently break historical audit queries.

This test locks the member→value map in code. To add a new event
type, append the member here too. To rename an existing one, you'll
need to write a data migration *and* update this test in the same PR.
"""

from __future__ import annotations

from app.core.audit_events import AuditEventType


EXPECTED_VALUES: dict[str, str] = {
    # Lifecycle
    "SESSION_CREATED": "session_created",
    "CONSENT_CONFIRMED": "consent_confirmed",
    "RECORDING_STARTED": "recording_started",
    "SESSION_PAUSED": "session_paused",
    "STAGE1_STARTED": "stage1_started",
    "STAGE1_DELIVERED": "stage1_delivered",
    "STAGE2_STARTED": "stage2_started",
    "FULL_NOTE_DELIVERED": "full_note_delivered",
    "NOTE_EXPORTED": "note_exported",
    "SESSION_PURGED": "session_purged",
    # Notes
    "STAGE1_APPROVED": "stage1_approved",
    "STAGE1_FAILED": "stage1_failed",
    "STAGE2_SKIPPED": "stage2_skipped",
    "STAGE2_COMPLETE": "stage2_complete",
    "STAGE2_FAILED": "stage2_failed",
    "NOTE_VERSION_CREATED": "note_version_created",
    "TEMPLATE_CHANGED": "template_changed",
    "CONFLICT_RESOLVED": "conflict_resolved",
    # Frames / masking
    "FRAME_UPLOADED": "frame_uploaded",
    "SCREEN_FRAME_PROCESSED": "screen_frame_processed",
    "MASKING_CONFIRMED": "masking_confirmed",
    # Transcription
    "TRANSCRIPTION_COMPLETE": "transcription_complete",
    "TRANSCRIPTION_FAILED": "transcription_failed",
    "S3_UPLOAD_FAILED": "s3_upload_failed",
    "PHI_AUDIT_COMPLETE": "phi_audit_complete",
    "SPEAKER_TAGS_APPLIED": "speaker_tags_applied",
    # Vision
    "VISION_FRAME_FAILED": "vision_frame_failed",
    "PROVIDER_FALLBACK": "provider_fallback",
    # Cleanup
    "AUDIO_PURGED": "audio_purged",
    "FRAMES_PURGED": "frames_purged",
    "EVAL_FRAMES_MIGRATED": "eval_frames_migrated",
    "CLEANUP_PARTIAL_FAILURE": "cleanup_partial_failure",
    # Privacy / account
    "BIOMETRIC_CONSENT_CONFIRMED": "biometric_consent_confirmed",
    "VOICE_ENROLLMENT_COMPLETE": "voice_enrollment_complete",
    "VOICE_ENROLLMENT_DELETED": "voice_enrollment_deleted",
    "ACCOUNT_DELETED": "account_deleted",
    # Admin
    "USER_CREATED": "user_created",
    "USER_UPDATED": "user_updated",
    "EVAL_SCORE_SUBMITTED": "eval_score_submitted",
    # System
    "CONFIG_CHANGED": "config_changed",
    "PROVIDER_CHANGED": "provider_changed",
}


def test_audit_event_type_values_locked() -> None:
    """Every existing member's value must stay byte-identical to the
    historical wire format. Rename = breaking change."""
    actual = {m.name: m.value for m in AuditEventType}
    assert actual == EXPECTED_VALUES, (
        "AuditEventType values drifted from the locked map. If you "
        "intentionally renamed a value, write a DynamoDB migration "
        "and update tests/unit/test_audit_events.py in the same PR."
    )


def test_audit_event_type_is_str_subclass() -> None:
    """StrEnum members must serialize identically to bare strings —
    the audit log path treats them as ``str`` when writing to DynamoDB."""
    assert issubclass(AuditEventType, str)
    assert AuditEventType.SESSION_CREATED == "session_created"
    assert f"{AuditEventType.STAGE1_DELIVERED}" == "stage1_delivered"


def test_state_audit_events_use_enum_members() -> None:
    """``STATE_AUDIT_EVENTS`` must reference enum members, not raw
    strings. Catches the easy regression where someone adds a new
    SessionState and bypasses the enum."""
    from app.modules.session.service import STATE_AUDIT_EVENTS

    for state, event in STATE_AUDIT_EVENTS.items():
        assert isinstance(event, AuditEventType), (
            f"STATE_AUDIT_EVENTS[{state!r}] should be an AuditEventType "
            f"member but was {type(event).__name__}: {event!r}"
        )

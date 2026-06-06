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

import os

import pytest

from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
    enforce_audit_kwargs,
    validate_audit_kwargs,
)

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
    "BULK_NOTE_EXPORT": "bulk_note_export",
    "EXTERNAL_REFERENCE_ID_SET": "external_reference_id_set",
    "MACRO_CREATED": "macro_created",
    "MACRO_UPDATED": "macro_updated",
    "MACRO_DELETED": "macro_deleted",
    "PATIENT_SUMMARY_GENERATED": "patient_summary_generated",
    "PATIENT_SUMMARY_EDITED": "patient_summary_edited",
    "ORDERS_EXTRACTED": "orders_extracted",
    "ORDER_CONFIRMED": "order_confirmed",
    "ORDER_EDITED": "order_edited",
    "ORDER_CANCELLED": "order_cancelled",
    "CODING_SUGGESTIONS_EXTRACTED": "coding_suggestions_extracted",
    "CODING_SUGGESTION_CONFIRMED": "coding_suggestion_confirmed",
    "CODING_SUGGESTION_REJECTED": "coding_suggestion_rejected",
    "CODING_SUGGESTION_EDITED": "coding_suggestion_edited",
    "EMR_WRITE_BACK_QUEUED": "emr_write_back_queued",
    "EMR_WRITE_BACK_SENT": "emr_write_back_sent",
    "EMR_WRITE_BACK_FAILED": "emr_write_back_failed",
    "LIVE_PREVIEW_GENERATED": "live_preview_generated",
    "SESSION_PURGED": "session_purged",
    "SESSION_DISCARDED": "session_discarded",
    # Clip evidence (dual-mode visual evidence, P1-1)
    "CLIP_UPLOADED": "clip_uploaded",
    "CLIP_MASKED": "clip_masked",
    "CLIP_DISCARDED": "clip_discarded",
    # Notes
    "STAGE1_APPROVED": "stage1_approved",
    "STAGE1_FAILED": "stage1_failed",
    # Stage 1 entry guards — no provider call when transcript is empty/low.
    "STAGE1_SKIPPED_NO_TRANSCRIPT": "stage1_skipped_no_transcript",
    "STAGE1_SKIPPED_LOW_TRANSCRIPT": "stage1_skipped_low_transcript",
    # Denormalized session-stats recompute trail.
    "SESSION_STATS_RECOMPUTED": "session_stats_recomputed",
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
    # Profile (#260) — team list edit (count delta only, never names)
    "TEAM_MEMBERS_UPDATED": "team_members_updated",
    # Admin
    "USER_CREATED": "user_created",
    "USER_UPDATED": "user_updated",
    "EVAL_SCORE_SUBMITTED": "eval_score_submitted",
    "EVAL_ASSIGNMENT_CREATED": "eval_assignment_created",
    "EVAL_ASSIGNMENT_REMOVED": "eval_assignment_removed",
    "EVAL_ASSIGNMENT_COMPLETED": "eval_assignment_completed",
    # System
    "CONFIG_CHANGED": "config_changed",
    "PROVIDER_CHANGED": "provider_changed",
    "PROVIDER_OVERRIDE_SET": "provider_override_set",
    "PROVIDER_OVERRIDE_CLEARED": "provider_override_cleared",
    # Card-visibility feature flag update (lane-full/card-visibility-flags).
    "FEATURE_FLAGS_UPDATED": "feature_flags_updated",
    "VISUAL_EVIDENCE_MODE_OVERRIDE_SET": "visual_evidence_mode_override_set",
    # Operator probes (P1-FU-GEMINI-PROBE)
    "VISION_CLIP_PROBED": "vision_clip_probed",
    # AI per-physician user prompt lifecycle (AI-PROMPTS-B, replacement
    # semantics — see app.modules.prompts).
    "PROMPT_USER_PROMPT_SET": "prompt_user_prompt_set",
    "PROMPT_USER_PROMPT_CLEARED": "prompt_user_prompt_cleared",
    # Longitudinal patient context (#61, full slice). Fires once per
    # Stage 1 note-gen call where prior encounters were consumed.
    "LONGITUDINAL_CONTEXT_LOADED": "longitudinal_context_loaded",
    # Auth pivot (AUTH-PIVOT-BACKEND) — every auth state change.
    "LOGIN_SUCCESS": "login_success",
    "LOGIN_FAILURE": "login_failure",
    "LOGIN_LOCKED": "login_locked",
    "LOGOUT": "logout",
    "MFA_ENROLLED": "mfa_enrolled",
    "MFA_RESET": "mfa_reset",
    # Portal MFA + sessions (#163) — self-serve disable + per-row /
    # bulk refresh-token revocation.
    "MFA_DISABLED": "mfa_disabled",
    "SESSION_REVOKED": "session_revoked",
    "SESSIONS_REVOKED_ALL": "sessions_revoked_all",
    "PASSWORD_RESET_REQUESTED": "password_reset_requested",
    "PASSWORD_CHANGED": "password_changed",
    "ADMIN_PASSWORD_RESET_ISSUED": "admin_password_reset_issued",
    "REFRESH_TOKEN_ISSUED": "refresh_token_issued",
    "REFRESH_TOKEN_ROTATED": "refresh_token_rotated",
    "REFRESH_TOKEN_REVOKED": "refresh_token_revoked",
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


# ── Q-03 — kwarg whitelist ────────────────────────────────────────────────


def test_every_audit_event_has_whitelist_entry() -> None:
    """OCP guard: every enum member must have an entry in
    ``ALLOWED_AUDIT_KWARGS``. Adding a new event without a whitelist
    entry trips this test until the gap is filled."""
    missing = [m for m in AuditEventType if m not in ALLOWED_AUDIT_KWARGS]
    assert not missing, (
        f"AuditEventType members missing from ALLOWED_AUDIT_KWARGS: "
        f"{[m.value for m in missing]}"
    )


def test_whitelist_only_lists_known_events() -> None:
    """Inverse guard: whitelist must not reference removed enum members."""
    known = set(AuditEventType)
    extras = [e for e in ALLOWED_AUDIT_KWARGS if e not in known]
    assert not extras, f"ALLOWED_AUDIT_KWARGS has stale entries: {extras}"


def test_validate_returns_empty_for_known_kwargs() -> None:
    unknown = validate_audit_kwargs(
        AuditEventType.STAGE1_APPROVED,
        ["version", "provider_used", "completeness_score"],
    )
    assert unknown == set()


def test_validate_returns_unknown_kwargs() -> None:
    unknown = validate_audit_kwargs(
        AuditEventType.STAGE1_APPROVED,
        ["version", "provideR_used", "completeness_score"],  # typo
    )
    assert unknown == {"provideR_used"}


def test_validate_is_permissive_for_raw_string_event_types() -> None:
    """Fallback path (unknown SessionState) emits a raw string event
    type; the validator can't whitelist what it doesn't know about,
    so it short-circuits with an empty set."""
    unknown = validate_audit_kwargs("state_changed_unknown", ["anything"])
    assert unknown == set()


def test_strict_mode_raises_on_unknown_kwargs(monkeypatch) -> None:
    """``AURION_AUDIT_STRICT=1`` (set by conftest) makes typos a
    hard error."""
    monkeypatch.setenv("AURION_AUDIT_STRICT", "1")
    with pytest.raises(ValueError, match="Unknown kwargs"):
        enforce_audit_kwargs(
            AuditEventType.STAGE1_APPROVED,
            {"version": 1, "typo_field": "x"},
        )


def test_strict_mode_passes_known_kwargs(monkeypatch) -> None:
    monkeypatch.setenv("AURION_AUDIT_STRICT", "1")
    # Should not raise.
    enforce_audit_kwargs(
        AuditEventType.STAGE1_APPROVED,
        {"version": 1, "provider_used": "anthropic", "completeness_score": 0.8},
    )


def test_non_strict_mode_logs_warning_but_does_not_raise(monkeypatch) -> None:
    """Production mode: log + continue. Losing an audit row to a typo
    would be worse than letting it through with an extra field.

    Patches the module-level logger directly instead of using caplog
    because caplog interacts poorly with other tests in the suite that
    install their own logging handlers (the test passes in isolation
    but caplog goes empty when chained behind specific siblings).
    """
    from unittest.mock import MagicMock

    from app.core import audit_events as ae

    monkeypatch.setenv("AURION_AUDIT_STRICT", "0")
    fake_logger = MagicMock()
    monkeypatch.setattr(ae, "logger", fake_logger)

    # Should not raise.
    enforce_audit_kwargs(
        AuditEventType.STAGE1_APPROVED,
        {"version": 1, "typo_field": "x"},
    )

    fake_logger.warning.assert_called_once()
    msg = fake_logger.warning.call_args[0][0]
    assert "Unknown kwargs" in msg
    assert "typo_field" in msg


def test_pytest_runs_with_strict_mode() -> None:
    """Top-level conftest must enable strict mode for the suite. This
    test fails if someone deletes the conftest or its setdefault."""
    assert os.getenv("AURION_AUDIT_STRICT") == "1", (
        "Strict mode should be enabled for the test suite via "
        "backend/tests/conftest.py — typos in audit kwargs must "
        "break the build, not slip through to CloudWatch."
    )

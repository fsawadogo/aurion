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

import logging
import os
from enum import StrEnum
from typing import Any, Iterable

logger = logging.getLogger("aurion.audit")


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
    BULK_NOTE_EXPORT = "bulk_note_export"
    EXTERNAL_REFERENCE_ID_SET = "external_reference_id_set"
    MACRO_CREATED = "macro_created"
    MACRO_UPDATED = "macro_updated"
    MACRO_DELETED = "macro_deleted"
    PATIENT_SUMMARY_GENERATED = "patient_summary_generated"
    PATIENT_SUMMARY_EDITED = "patient_summary_edited"
    ORDERS_EXTRACTED = "orders_extracted"
    ORDER_CONFIRMED = "order_confirmed"
    ORDER_EDITED = "order_edited"
    ORDER_CANCELLED = "order_cancelled"
    CODING_SUGGESTIONS_EXTRACTED = "coding_suggestions_extracted"
    CODING_SUGGESTION_CONFIRMED = "coding_suggestion_confirmed"
    CODING_SUGGESTION_REJECTED = "coding_suggestion_rejected"
    CODING_SUGGESTION_EDITED = "coding_suggestion_edited"
    SESSION_PURGED = "session_purged"
    SESSION_DISCARDED = "session_discarded"

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
    EVAL_ASSIGNMENT_CREATED = "eval_assignment_created"
    EVAL_ASSIGNMENT_REMOVED = "eval_assignment_removed"
    EVAL_ASSIGNMENT_COMPLETED = "eval_assignment_completed"

    # ── System / config ──────────────────────────────────────────────────
    CONFIG_CHANGED = "config_changed"
    PROVIDER_CHANGED = "provider_changed"
    PROVIDER_OVERRIDE_SET = "provider_override_set"
    PROVIDER_OVERRIDE_CLEARED = "provider_override_cleared"


# ── Q-03 — kwarg whitelist ────────────────────────────────────────────────
#
# Maps each event type to the set of kwargs ``write_audit(**fields)``
# may carry. Derived from the real call sites; expanding an entry is
# fine, deleting one is a breaking change for any consumer that depends
# on the existing field.
#
# Three flavors:
#   - State-machine transitions (RECORDING_STARTED, SESSION_PAUSED,
#     STAGE1_STARTED, FULL_NOTE_DELIVERED at the route level, …) — emitted
#     by ``write_audit(session.id, get_audit_event_for_state(state))`` with
#     no kwargs.
#   - Server-emitted feature events — the kwargs match the
#     write_audit/audit.write_event calls in routes + services.
#   - iOS-emitted events (``MASKING_CONFIRMED``,
#     ``BIOMETRIC_CONSENT_CONFIRMED``, ``VOICE_ENROLLMENT_*``) — the
#     server never emits these via ``write_audit``; the whitelist is
#     ``frozenset()`` so that if the server ever does, no fields slip
#     through unannounced.

ALLOWED_AUDIT_KWARGS: dict[AuditEventType, frozenset[str]] = {
    # Lifecycle (state transitions write with no kwargs)
    AuditEventType.SESSION_CREATED: frozenset({"clinician_id", "specialty"}),
    AuditEventType.CONSENT_CONFIRMED: frozenset({"consent_method"}),
    AuditEventType.RECORDING_STARTED: frozenset(),
    AuditEventType.SESSION_PAUSED: frozenset(),
    AuditEventType.STAGE1_STARTED: frozenset(),
    AuditEventType.STAGE1_DELIVERED: frozenset({"stage1_latency_ms"}),
    AuditEventType.STAGE2_STARTED: frozenset({"job_id"}),
    AuditEventType.FULL_NOTE_DELIVERED: frozenset(
        {"version", "provider_used", "completeness_score"}
    ),
    AuditEventType.NOTE_EXPORTED: frozenset(
        # Server path emits format/version/stage; iOS audit endpoint adds
        # bytes_produced + origin. Union of both paths.
        {"format", "version", "stage", "bytes_produced", "origin"}
    ),
    # Bulk export from the web portal — anchors on the first session_id
    # but carries the full included/skipped lists so the audit trail
    # tells the whole story in one row.
    AuditEventType.BULK_NOTE_EXPORT: frozenset(
        {"included_session_ids", "skipped_session_ids", "actor_id"}
    ),
    # Patient identifier (external_reference_id) set or cleared. We do
    # NOT carry the identifier value itself — it's PHI; the row id +
    # actor_id + cleared bool is enough for the audit story without
    # leaking who-is-which-patient into the immutable trail.
    AuditEventType.EXTERNAL_REFERENCE_ID_SET: frozenset(
        {"actor_id", "cleared"}
    ),
    # Macro lifecycle — never carry the body itself (might be
    # personal-style phrasing the physician wouldn't want quoted in
    # an audit query). Capturing `macro_id` + `shortcut` + actor is
    # enough to reconstruct the change set.
    AuditEventType.MACRO_CREATED: frozenset(
        {"actor_id", "macro_id", "shortcut", "specialty"}
    ),
    AuditEventType.MACRO_UPDATED: frozenset(
        {"actor_id", "macro_id", "shortcut", "specialty"}
    ),
    AuditEventType.MACRO_DELETED: frozenset(
        {"actor_id", "macro_id", "shortcut"}
    ),
    # Patient summary lifecycle — never carry the body text; the
    # summary itself is PHI and would be permanent in the audit log.
    # version + provider_used are the audit-trail-meaningful fields.
    AuditEventType.PATIENT_SUMMARY_GENERATED: frozenset(
        {"actor_id", "version", "provider_used"}
    ),
    AuditEventType.PATIENT_SUMMARY_EDITED: frozenset(
        {"actor_id", "version"}
    ),
    # Orders extraction + lifecycle. The `details` JSON is PHI-adjacent
    # (drug, dose, body part, indication) — never carried into the
    # audit. kind + status + actor + order_id + count are enough for
    # the audit trail.
    AuditEventType.ORDERS_EXTRACTED: frozenset(
        {"actor_id", "count", "provider_used"}
    ),
    AuditEventType.ORDER_CONFIRMED: frozenset(
        {"actor_id", "order_id", "kind"}
    ),
    AuditEventType.ORDER_EDITED: frozenset(
        {"actor_id", "order_id", "kind"}
    ),
    AuditEventType.ORDER_CANCELLED: frozenset(
        {"actor_id", "order_id", "kind"}
    ),
    # Coding suggestions lifecycle. The `code` itself is NOT PHI (it's
    # a billing code string) and IS allowed in the audit row — knowing
    # which code was confirmed/rejected/edited is the whole point of
    # the trail for a billing dispute. But `description` and
    # `justification` ARE PHI-adjacent (they paraphrase the patient's
    # clinical content) and are deliberately excluded.
    AuditEventType.CODING_SUGGESTIONS_EXTRACTED: frozenset(
        {"actor_id", "count", "provider_used"}
    ),
    AuditEventType.CODING_SUGGESTION_CONFIRMED: frozenset(
        {"actor_id", "suggestion_id", "code_system", "code"}
    ),
    AuditEventType.CODING_SUGGESTION_REJECTED: frozenset(
        {"actor_id", "suggestion_id", "code_system", "code"}
    ),
    # On edit we audit both the prior and new code so the trail
    # reconstructs the physician's override decision without needing
    # to join against the row history.
    AuditEventType.CODING_SUGGESTION_EDITED: frozenset(
        {"actor_id", "suggestion_id", "code_system", "previous_code", "new_code"}
    ),
    AuditEventType.SESSION_PURGED: frozenset(),
    AuditEventType.SESSION_DISCARDED: frozenset({"prior_state"}),
    # Notes / review
    AuditEventType.STAGE1_APPROVED: frozenset(
        {"version", "provider_used", "completeness_score"}
    ),
    AuditEventType.STAGE1_FAILED: frozenset({"reason"}),
    AuditEventType.STAGE2_SKIPPED: frozenset({"reason"}),
    AuditEventType.STAGE2_COMPLETE: frozenset(
        {
            "frames",
            "conflicts",
            "reason",
            "frames_processed",
            "frames_discarded",
            "enriches",
            "repeats",
            "unresolved_conflicts",
        }
    ),
    AuditEventType.STAGE2_FAILED: frozenset(
        {"job_id", "reason", "total_frames", "failed_frames"}
    ),
    AuditEventType.NOTE_VERSION_CREATED: frozenset({"version", "sections_edited"}),
    AuditEventType.TEMPLATE_CHANGED: frozenset({"new_specialty"}),
    AuditEventType.CONFLICT_RESOLVED: frozenset({"claim_id", "action", "new_version"}),
    # Frames / masking
    AuditEventType.FRAME_UPLOADED: frozenset(
        {
            "timestamp_ms",
            "bytes",
            "frame_type",
            "masking_status",
            "faces_detected",
            "phi_regions_redacted",
        }
    ),
    AuditEventType.SCREEN_FRAME_PROCESSED: frozenset(
        {
            "frame_id",
            "timestamp_ms",
            "screen_type",
            "integration_status",
            "claims_added",
            "frame_type",
            "masking_status",
            "phi_regions_redacted",
        }
    ),
    # iOS-only — server never emits these via write_audit
    AuditEventType.MASKING_CONFIRMED: frozenset(),
    # Transcription
    AuditEventType.TRANSCRIPTION_COMPLETE: frozenset({"provider_used", "segment_count"}),
    AuditEventType.TRANSCRIPTION_FAILED: frozenset({"error_message"}),
    AuditEventType.S3_UPLOAD_FAILED: frozenset({"error_message"}),
    AuditEventType.PHI_AUDIT_COMPLETE: frozenset({"phi_detected"}),
    AuditEventType.SPEAKER_TAGS_APPLIED: frozenset({"segments_updated", "segments_unknown"}),
    # Vision
    AuditEventType.VISION_FRAME_FAILED: frozenset({"frame_id", "error_message"}),
    AuditEventType.PROVIDER_FALLBACK: frozenset(
        {"frame_id", "original_error", "fallback_provider"}
    ),
    # Cleanup
    AuditEventType.AUDIO_PURGED: frozenset({"bucket", "s3_key"}),
    AuditEventType.FRAMES_PURGED: frozenset({"bucket", "frame_count"}),
    AuditEventType.EVAL_FRAMES_MIGRATED: frozenset(
        {"source_bucket", "dest_bucket", "frame_count"}
    ),
    AuditEventType.CLEANUP_PARTIAL_FAILURE: frozenset(
        {"bucket", "s3_key", "error_message", "failed_count"}
    ),
    # Privacy / account — iOS-only voice events stay empty
    AuditEventType.BIOMETRIC_CONSENT_CONFIRMED: frozenset(),
    AuditEventType.VOICE_ENROLLMENT_COMPLETE: frozenset(),
    AuditEventType.VOICE_ENROLLMENT_DELETED: frozenset(),
    AuditEventType.ACCOUNT_DELETED: frozenset(
        {
            "clinician_id",
            "deleted_sessions",
            "deleted_note_versions",
            "deleted_pilot_metrics",
            "deleted_s3_objects",
            "retention_note",
        }
    ),
    # Admin
    AuditEventType.USER_CREATED: frozenset(
        {"target_user_id", "target_email", "target_role", "created_by"}
    ),
    AuditEventType.USER_UPDATED: frozenset(
        {"target_user_id", "changes", "updated_by"}
    ),
    AuditEventType.EVAL_SCORE_SUBMITTED: frozenset({"overall_score", "scored_by"}),
    AuditEventType.EVAL_ASSIGNMENT_CREATED: frozenset(
        {"assignee_email", "assigned_by"}
    ),
    AuditEventType.EVAL_ASSIGNMENT_REMOVED: frozenset(
        {"assignee_email", "removed_by"}
    ),
    AuditEventType.EVAL_ASSIGNMENT_COMPLETED: frozenset(
        {"assignee_email", "completed_via_score"}
    ),
    # System (admin write-through; kwargs vary, kept permissive)
    AuditEventType.CONFIG_CHANGED: frozenset({"changed_by", "diff"}),
    AuditEventType.PROVIDER_CHANGED: frozenset(
        {"changed_by", "provider_role", "old_provider", "new_provider"}
    ),
    AuditEventType.PROVIDER_OVERRIDE_SET: frozenset(
        {"changed_by", "provider_type", "new_provider", "reason"}
    ),
    AuditEventType.PROVIDER_OVERRIDE_CLEARED: frozenset(
        {"changed_by", "provider_type", "old_provider"}
    ),
}


# Strict mode raises on unknown kwargs instead of warning. Pytest's
# conftest enables it for the whole test suite; production runs
# without (the warning trail is enough — losing an audit row to a
# typo is worse than landing one with an extra field).
_STRICT_ENV = "AURION_AUDIT_STRICT"


def _strict_mode_enabled() -> bool:
    return os.getenv(_STRICT_ENV, "").lower() in ("1", "true", "yes")


def validate_audit_kwargs(
    event_type: AuditEventType | str,
    fields: Iterable[str],
) -> set[str]:
    """Return the set of kwarg names that aren't in the whitelist.

    For raw-string event types (the fallback path for unknown
    SessionStates in ``get_audit_event_for_state``) the validator is
    permissive — there's no whitelist to check against.
    """
    if not isinstance(event_type, AuditEventType):
        return set()
    allowed = ALLOWED_AUDIT_KWARGS.get(event_type)
    if allowed is None:
        return set()
    return {key for key in fields if key not in allowed}


def enforce_audit_kwargs(
    event_type: AuditEventType | str,
    fields: dict[str, Any],
) -> None:
    """Log (or raise in strict mode) when ``fields`` contains kwargs
    outside the whitelist for ``event_type``. Called from
    ``write_audit`` so every emission site is covered."""
    unknown = validate_audit_kwargs(event_type, fields.keys())
    if not unknown:
        return
    msg = (
        f"Unknown kwargs for audit event {event_type!s}: "
        f"{sorted(unknown)}. Update ALLOWED_AUDIT_KWARGS or fix the typo."
    )
    if _strict_mode_enabled():
        raise ValueError(msg)
    logger.warning(msg)

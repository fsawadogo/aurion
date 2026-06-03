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
    EMR_WRITE_BACK_QUEUED = "emr_write_back_queued"
    EMR_WRITE_BACK_SENT = "emr_write_back_sent"
    EMR_WRITE_BACK_FAILED = "emr_write_back_failed"
    LIVE_PREVIEW_GENERATED = "live_preview_generated"
    SESSION_PURGED = "session_purged"
    SESSION_DISCARDED = "session_discarded"
    # ── Clip evidence (dual-mode visual evidence, P1-1) ───────────────────
    # Parallel to FRAME_UPLOADED / MASKING_CONFIRMED / VISION_FRAME_FAILED:
    # CLIP_UPLOADED  fires after a masked clip lands in S3 (server-emitted)
    # CLIP_MASKED    is the iOS-emitted equivalent of MASKING_CONFIRMED for
    #                clips — empty kwargs whitelist, iOS pushes only the
    #                clip-level masking_metadata into the audit row body
    # CLIP_DISCARDED fires when a clip's caption confidence is below
    #                threshold and the clip drops out of Stage 2 (parallels
    #                the FRAME_DISCARDED path inside the vision service)
    CLIP_UPLOADED = "clip_uploaded"
    CLIP_MASKED = "clip_masked"
    CLIP_DISCARDED = "clip_discarded"

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
    # Per-session `visual_evidence_mode` override (dual-mode plan, P1-7).
    # Fires when a clinician/eval-team caller creates a session whose
    # `provider_overrides.visual_evidence_mode` is set — flips the Stage 2
    # dispatch for THIS session only without touching AppConfig. Gated by
    # `feature_flags.per_session_visual_evidence_mode_override`; when the
    # flag is False the API returns 400 before this event can fire.
    VISUAL_EVIDENCE_MODE_OVERRIDE_SET = "visual_evidence_mode_override_set"
    # Operator probe of the configured `vision_clip` provider
    # (P1-FU-GEMINI-PROBE). Fires once per probe call (success OR
    # failure) so we have a durable trail of who probed which provider
    # at what latency. No clip body, no PHI, no session linkage —
    # the synthetic session id `00000000-0000-0000-0000-000000000000`
    # is used to keep the row out of any real session's history.
    VISION_CLIP_PROBED = "vision_clip_probed"
    # Per-physician AI Prompt overlay set / cleared (AI-PROMPTS-B).
    # Fires when a clinician saves or resets an append-only overlay on
    # one of the catalog prompts via PATCH/DELETE /me/prompts/{id}.
    # The overlay text itself is NEVER carried into the audit row —
    # only ``prompt_id`` + ``overlay_length`` + ``actor_id``. Personal
    # phrasing stays out of the immutable trail. Like
    # ``VISION_CLIP_PROBED`` these events are not session-scoped; the
    # synthetic session id ``00000000-0000-0000-0000-000000000000``
    # keeps the row out of any real session's history.
    PROMPT_OVERRIDE_SET = "prompt_override_set"
    PROMPT_OVERRIDE_CLEARED = "prompt_override_cleared"


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
    # EMR write-back lifecycle. We carry the connector key + external
    # (EMR-side) id when the connector returned one — those are the
    # traceability hooks for a billing or chart-mismatch dispute. The
    # payload itself is NOT in the audit row (it's the note's PHI); we
    # store a sha256 fingerprint instead so the audit chain ties to a
    # specific serialization without persisting the serialization.
    AuditEventType.EMR_WRITE_BACK_QUEUED: frozenset(
        {"actor_id", "write_back_id", "connector", "payload_fingerprint"}
    ),
    AuditEventType.EMR_WRITE_BACK_SENT: frozenset(
        {
            "actor_id",
            "write_back_id",
            "connector",
            "external_id",
            "attempt_count",
        }
    ),
    AuditEventType.EMR_WRITE_BACK_FAILED: frozenset(
        {
            "actor_id",
            "write_back_id",
            "connector",
            "error_reason",
            "attempt_count",
        }
    ),
    # Live preview generated. Carries version + transcript_chars +
    # provider for the "preview quality over time" pilot chart. Never
    # the preview content itself (it's PHI; lives only in the row's
    # JSONB column).
    AuditEventType.LIVE_PREVIEW_GENERATED: frozenset(
        {
            "actor_id",
            "preview_id",
            "version",
            "transcript_chars",
            "provider_used",
            "latency_ms",
        }
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
    # Clip evidence (P1-1).
    # CLIP_UPLOADED is server-emitted and carries the same masking-proof
    # fields as FRAME_UPLOADED plus the clip-level metadata. Duration +
    # trigger anchor + face counts are the audit-trail-meaningful fields;
    # the clip body itself is in S3 (with its own KMS + TTL policy).
    AuditEventType.CLIP_UPLOADED: frozenset(
        {
            "timestamp_ms",
            "bytes",
            "duration_ms",
            "trigger_segment_id",
            "masking_status",
            "frames_total",
            "frames_with_faces",
            "faces_blurred",
        }
    ),
    # CLIP_MASKED is iOS-emitted — server never writes it via write_audit.
    # Empty whitelist matches MASKING_CONFIRMED for the same reason.
    AuditEventType.CLIP_MASKED: frozenset(),
    # CLIP_DISCARDED is server-emitted from the Stage 2 vision service
    # when a clip caption confidence is below threshold. Carries the
    # clip's S3 key and the confidence reason so the eval team can
    # post-hoc analyze what dropped out.
    AuditEventType.CLIP_DISCARDED: frozenset(
        {"s3_key", "confidence", "confidence_reason"}
    ),
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
    # Per-session visual_evidence_mode override (P1-7). Carries the actor
    # (clinician or eval-team UUID) + their role + the chosen mode. The
    # mode is one of the VisualEvidenceMode enum string values. No PHI.
    AuditEventType.VISUAL_EVIDENCE_MODE_OVERRIDE_SET: frozenset(
        {"actor_id", "actor_role", "mode"}
    ),
    # Operator probe of the configured `vision_clip` provider
    # (P1-FU-GEMINI-PROBE). `provider` is the resolved provider key
    # string (e.g. "gemini"); `success` is a boolean; `latency_ms` is
    # the wall-clock around the provider call; `error_type` is the
    # classified exception name when success is false (else absent).
    AuditEventType.VISION_CLIP_PROBED: frozenset(
        {"provider", "success", "latency_ms", "error_type"}
    ),
    # AI prompt overlay lifecycle (AI-PROMPTS-B). ``actor_id`` is the
    # owning clinician's UUID; ``prompt_id`` is the registry key the
    # overlay targets; ``overlay_length`` is a small integer (char
    # count). The overlay TEXT itself is deliberately excluded — it's
    # personal phrasing the physician wouldn't want quoted in an audit
    # query, and the length is sufficient for the "did anything change?"
    # audit story. CLEARED doesn't carry overlay_length (it's zero by
    # definition) — the actor_id + prompt_id pair is enough.
    AuditEventType.PROMPT_OVERRIDE_SET: frozenset(
        {"actor_id", "prompt_id", "overlay_length"}
    ),
    AuditEventType.PROMPT_OVERRIDE_CLEARED: frozenset(
        {"actor_id", "prompt_id"}
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

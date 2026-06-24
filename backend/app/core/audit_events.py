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
    CUSTOM_TEMPLATE_CREATED = "custom_template_created"
    CUSTOM_TEMPLATE_UPDATED = "custom_template_updated"
    CUSTOM_TEMPLATE_DELETED = "custom_template_deleted"
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
    # Admin hard-delete of ANY clinician's session (compliance/admin action,
    # distinct from a clinician self-discarding their own). Append-only: the
    # deletion is recorded here while the session rows + media are erased.
    ADMIN_SESSION_DELETED = "admin_session_deleted"
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
    # Clip-pipeline drop-site telemetry (#390). Distinguishes "the device
    # never attempted a clip" from "the device attempted but dropped it
    # client-side" — every prior server signal (S3 object, CLIP_UPLOADED,
    # pilot_metrics, CLIP_DISCARDED) sits DOWNSTREAM of a successful upload,
    # so a zero-clips session was previously a black box (cost a full
    # investigation in #324). All three are count-only / enum-only — never
    # PHI, never an S3 key or body.
    #   CLIP_DROPPED        a single drop, with a reason enum. iOS emits it
    #                       for the once-per-session driver-not-started
    #                       reasons; the server emits it on the S3 PutObject
    #                       failure path in clips.py (origin distinguishes).
    #   CLIP_PIPELINE_SUMMARY  flushed by iOS on stop — the per-session
    #                       pipeline counters (frames appended / clips
    #                       extracted / masked / uploaded / dropped-by-reason)
    #                       so per-tick drops are visible in aggregate without
    #                       a beacon storm during recording.
    #   CLIP_CONFIG_SNAPSHOT  the resolved clip config + app build captured at
    #                       record-start, so a stale AppConfig snapshot or an
    #                       old build is visible server-side (the #324 root
    #                       cause was a config field the device defaulted away).
    CLIP_DROPPED = "clip_dropped"
    CLIP_PIPELINE_SUMMARY = "clip_pipeline_summary"
    CLIP_CONFIG_SNAPSHOT = "clip_config_snapshot"

    # ── Notes / review ───────────────────────────────────────────────────
    STAGE1_APPROVED = "stage1_approved"
    STAGE1_FAILED = "stage1_failed"
    # Stage 1 entry guards — fire BEFORE any provider call when the
    # transcript is empty/missing or too short. We never want a
    # generative model called with zero source material (CLAUDE.md
    # §"The Single Most Important Constraint"); these events document
    # that the guard fired and the provider was not invoked. Counted
    # alongside STAGE1_FAILED in compliance reports.
    STAGE1_SKIPPED_NO_TRANSCRIPT = "stage1_skipped_no_transcript"
    STAGE1_SKIPPED_LOW_TRANSCRIPT = "stage1_skipped_low_transcript"
    # Stage 1 produced a structurally-valid but EMPTY note (zero populated
    # required sections) — delivered, not failed, but no longer a silent
    # "success". Makes the empty-note rate visible + CloudWatch-alarmable
    # (#280: 7/16 recent notes were completeness=0.00 with no signal).
    # PHI-free payload: counts + score only, never transcript/claim text.
    STAGE1_EMPTY_NOTE = "stage1_empty_note"
    # Debug-tier event emitted when the live session-stats recompute
    # helper actually changed at least one downstream count. Carries
    # the new completeness numerator + denominator (PHI-free) so the
    # eval team can see "this approve/edit just flipped completeness
    # from 4/6 to 5/6" without diffing two note versions. Only emitted
    # on actual change (no-op cases stay silent to keep the audit log
    # quiet).
    SESSION_STATS_RECOMPUTED = "session_stats_recomputed"
    STAGE2_SKIPPED = "stage2_skipped"
    STAGE2_COMPLETE = "stage2_complete"
    STAGE2_FAILED = "stage2_failed"
    NOTE_VERSION_CREATED = "note_version_created"
    TEMPLATE_CHANGED = "template_changed"
    # Session create resolved a chosen context whose pinned template_key is
    # no longer an available built-in template; we coerced to the specialty
    # default (#314, B2). Count-only — the row's existence IS the signal, no
    # kwargs (never the context id, template name, or visit-type label).
    SESSION_TEMPLATE_KEY_COERCED = "session_template_key_coerced"
    CONFLICT_RESOLVED = "conflict_resolved"

    # ── Frames / masking ─────────────────────────────────────────────────
    FRAME_UPLOADED = "frame_uploaded"
    SCREEN_FRAME_PROCESSED = "screen_frame_processed"
    MASKING_CONFIRMED = "masking_confirmed"
    # iOS-emitted masking FAILURE provenance (AUR-API-CLIENT-AUDIT). These
    # are the compliance-critical complement to MASKING_CONFIRMED /
    # FRAME_UPLOADED: a frame whose on-device masking FAILED is dropped
    # fail-closed and NEVER uploaded, so the server has no other record it
    # ever existed. iOS posts these via POST /sessions/{id}/client-audit-events
    # so the PHI-masking report can prove dropped frames were discarded, not
    # leaked. PHI-free: a bounded ``failure_reason`` enum + count fields only,
    # never an image, S3 key, or body.
    #   MASKING_FAILED           one frame/screen/clip failed to mask + was dropped.
    #   MASKING_FAILURE_RETRIED  the physician re-ran masking on quarantined frames.
    #   MASKING_FAILURE_SKIPPED  the physician discarded quarantined frames unmasked.
    MASKING_FAILED = "masking_failed"
    MASKING_FAILURE_RETRIED = "masking_failure_retried"
    MASKING_FAILURE_SKIPPED = "masking_failure_skipped"

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
    # ── Windowed media retention (#338) ───────────────────────────────────
    # A retained-media replay URL was minted for a reviewer (currently the
    # audio-replay endpoint; the kwarg whitelist also names clip/frame for
    # the same surface). Carries the actor UUID, the evidence kind, and the
    # signed-URL TTL — NEVER an S3 key, signed URL, or any object body. The
    # row's existence is the audit signal that someone re-listened to / re-
    # watched retained media during review.
    EVIDENCE_REPLAYED = "evidence_replayed"
    # An admin/eval reviewer minted DOWNLOAD URLs for a session's retained
    # media via the admin "Captured Media" page (#338). Distinct from
    # EVIDENCE_REPLAYED (the in-review clinician audio-replay surface): this
    # is the cross-clinician admin download surface, ADMIN + EVAL_TEAM only.
    # Carries the actor UUID, the evidence kind ("session_media"), and the
    # PHI-free object counts (audio_count + clip_count) — NEVER an S3 key,
    # signed URL, or any object body. The row's existence is the audit
    # signal that a reviewer pulled download links for the raw media.
    EVIDENCE_DOWNLOADED = "evidence_downloaded"

    # ── Privacy / account ────────────────────────────────────────────────
    BIOMETRIC_CONSENT_CONFIRMED = "biometric_consent_confirmed"
    VOICE_ENROLLMENT_COMPLETE = "voice_enrollment_complete"
    VOICE_ENROLLMENT_DELETED = "voice_enrollment_deleted"
    ACCOUNT_DELETED = "account_deleted"

    # ── Profile (per-clinician preferences) ──────────────────────────────
    # Allied-health team list changed via PUT /profile (#260). Names are
    # workforce data — not PHI in the strict HIPAA sense, but unnecessary
    # in an immutable audit row. We carry only the actor UUID and the
    # before/after row counts so compliance can see "this clinician
    # changed their team list at T" without any names ever landing in
    # DynamoDB. Same posture MACRO_CREATED takes with the macro body and
    # PROMPT_USER_PROMPT_SET takes with the prompt text.
    TEAM_MEMBERS_UPDATED = "team_members_updated"
    # Consultation-types list changed via PUT /profile (#259). The list is
    # a mix of canonical default keys ("new_patient", "follow_up", "pre_op",
    # "post_op") and clinician-authored free-text labels (Marie: "LL new pt",
    # Perry: "breast visit"). The free-text labels are user-authored and
    # could in the worst case carry PHI even with the format gates; we
    # therefore carry ONLY count deltas in the audit row, never the
    # labels themselves. Same posture TEAM_MEMBERS_UPDATED (names),
    # MACRO_CREATED (body), and PROMPT_USER_PROMPT_SET (text) take.
    PROFILE_CONSULTATION_TYPES_UPDATED = "profile_consultation_types_updated"
    # Visit-type → context → template map changed via PUT /profile (#313,
    # B1; #318, B3). Each context carries a clinician-authored ``label``
    # (gated by the same PHI format checks as consultation types) and
    # binds EITHER a built-in ``template_key`` OR a custom ``template_ref``
    # (the B3 custom-template pointer). Labels, keys, refs, and context ids
    # are user-authored and could in the worst case carry PHI; we therefore
    # carry ONLY aggregate count deltas in the audit row — never labels,
    # keys, refs, ids, or template names. Same count-only posture
    # TEAM_MEMBERS_UPDATED (names) and PROFILE_CONSULTATION_TYPES_UPDATED
    # (labels) take.
    PROFILE_CONTEXTS_UPDATED = "profile_contexts_updated"

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
    # ADMIN flipped one or more card-visibility feature flags via the
    # web portal's /admin/feature-flags endpoint
    # (lane-full/card-visibility-flags). The kwarg whitelist below
    # carries ONLY the names of the fields that changed plus the
    # AppConfig hosted-version that the change produced — never the
    # truthy/falsy values themselves. Field names are config metadata,
    # not PHI; the values are not in the audit row by design (the
    # AppConfig hosted version is the source of truth and is itself
    # versioned in AWS).
    FEATURE_FLAGS_UPDATED = "feature_flags_updated"
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
    # Per-physician AI user prompt set / cleared (AI-PROMPTS-B,
    # replacement semantics). Fires when a clinician saves or resets
    # their REPLACEMENT user prompt on one of the catalog prompts via
    # PATCH/DELETE /me/prompts/{id}. The user prompt text itself is
    # NEVER carried into the audit row — only ``prompt_id`` +
    # ``user_prompt_length`` + ``actor_id``. Personal phrasing stays
    # out of the immutable trail. Like ``VISION_CLIP_PROBED`` these
    # events are not session-scoped; the synthetic session id
    # ``00000000-0000-0000-0000-000000000000`` keeps the row out of
    # any real session's history.
    PROMPT_USER_PROMPT_SET = "prompt_user_prompt_set"
    PROMPT_USER_PROMPT_CLEARED = "prompt_user_prompt_cleared"
    # Prompt Studio (create & share, #524) — an admin published a prompt
    # version to a cohort (self / role / all). Provenance only: actor + job +
    # version_no + scope (+ target_role for ROLE). NEVER the prompt text.
    PROMPT_STUDIO_PUBLISHED = "prompt_studio_published"
    # ── Auth pivot (backend JWT + TOTP + password reset) ──────────────────
    # Replaces the Cognito-managed flow. Every auth state change writes
    # one of these. Emitted with the synthetic session id
    # ``00000000-0000-0000-0000-000000000000`` because auth events are
    # not session-scoped (same pattern as PROMPT_USER_PROMPT_*). Email
    # NEVER appears in the kwargs — only actor_id / target_user_id UUIDs.
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGIN_LOCKED = "login_locked"
    LOGOUT = "logout"
    MFA_ENROLLED = "mfa_enrolled"
    MFA_RESET = "mfa_reset"
    # Self-serve MFA disable from /me/mfa (#163). Distinct from MFA_RESET
    # (admin-initiated) so the post-pilot security review can tell the
    # two apart in the trail.
    MFA_DISABLED = "mfa_disabled"
    # Per-row + bulk refresh-token revocation from the portal sessions
    # card (#163). SESSION_REVOKED carries the row id of the killed
    # token; SESSIONS_REVOKED_ALL carries the count of rows killed.
    # Distinct from REFRESH_TOKEN_REVOKED (which is the /auth/logout
    # path, single-token, by-token-presented) so the user-initiated
    # "sign out everywhere" gesture is queryable on its own.
    SESSION_REVOKED = "session_revoked"
    SESSIONS_REVOKED_ALL = "sessions_revoked_all"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_CHANGED = "password_changed"
    ADMIN_PASSWORD_RESET_ISSUED = "admin_password_reset_issued"
    REFRESH_TOKEN_ISSUED = "refresh_token_issued"
    REFRESH_TOKEN_ROTATED = "refresh_token_rotated"
    REFRESH_TOKEN_REVOKED = "refresh_token_revoked"
    # Longitudinal patient context loaded into Stage 1 note generation
    # (#61, full slice). Emitted once per Stage 1 call when at least
    # one prior encounter was actually fed into the LLM prompt. The
    # kwarg whitelist (``encounters_count`` + ``last_encounter_date``)
    # carries only the slim PHI-free signal that lets pilot analysis
    # measure how often the prior-context branch fires. NEVER carries
    # the identifier value, the prior session ids, or any clinical
    # content.
    LONGITUDINAL_CONTEXT_LOADED = "longitudinal_context_loaded"

    # ── #63 on-device visual measurement (wound L/W + ROM) ──────────────
    # Provenance for the measurement lifecycle. PHI-free: kwargs carry the
    # opaque measurement_id + descriptive metadata (kind/method/unit/
    # confidence/masking_status/reason) — NEVER the numeric value. A
    # measurement joined to a session is derived PHI (design §6.2); the
    # value lives only in the MeasurementCitation, behind KMS + the same
    # purge/erasure path as notes. GENERATED = computed on-device;
    # REVIEWED = physician confirmed/rejected; EDITED = physician nudged an
    # endpoint/angle; SUPPRESSED = below the refusal bar (not_measurable).
    MEASUREMENT_GENERATED = "measurement_generated"
    MEASUREMENT_REVIEWED = "measurement_reviewed"
    MEASUREMENT_EDITED = "measurement_edited"
    MEASUREMENT_SUPPRESSED = "measurement_suppressed"

    # ── Web-portal video import (VID-01…) ─────────────────────────────────
    # Provenance for an uploaded-encounter-video import job. PHI-free:
    #   VIDEO_IMPORT_STARTED  brackets the job (actor UUID only).
    #   VIDEO_IMPORT_COMPLETE  carries frame counts (server-side masking
    #                          slice) — never an S3 key or body.
    #   VIDEO_IMPORT_FAILED    a bounded reason string.
    #   CONSENT_ATTESTED       the clinician attested consent was obtained at
    #                          the original recording (the import substitute
    #                          for the bypassed live consent gate). Distinct
    #                          from CONSENT_CONFIRMED so compliance can tell
    #                          attested consent from live consent.
    #   RAW_VIDEO_PURGED       the uploaded raw video was deleted from S3
    #                          after extraction (bucket + key only).
    VIDEO_IMPORT_STARTED = "video_import_started"
    VIDEO_IMPORT_COMPLETE = "video_import_complete"
    VIDEO_IMPORT_FAILED = "video_import_failed"
    CONSENT_ATTESTED = "consent_attested"
    RAW_VIDEO_PURGED = "raw_video_purged"
    # Server-side masking provenance (VID-04 — the trust-boundary change).
    # The server (not iOS) masked an extracted frame. SERVER_MASKING_APPLIED
    # fires per stored frame (faces detected/blurred + timestamp); _FAILED
    # fires per dropped frame (bounded reason). PHI-free: counts + timestamp +
    # reason only, never an image or S3 key. These let compliance prove 100%
    # server-side masking before any frame reached a vision provider.
    SERVER_MASKING_APPLIED = "server_masking_applied"
    SERVER_MASKING_FAILED = "server_masking_failed"


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
    # #63 measurement lifecycle — PHI-free provenance only (NEVER the value).
    AuditEventType.MEASUREMENT_GENERATED: frozenset(
        {"measurement_id", "kind", "method", "unit", "confidence",
         "scale_source", "masking_status"}
    ),
    AuditEventType.MEASUREMENT_REVIEWED: frozenset(
        {"measurement_id", "kind", "physician_confirmed"}
    ),
    AuditEventType.MEASUREMENT_EDITED: frozenset({"measurement_id", "kind", "method"}),
    AuditEventType.MEASUREMENT_SUPPRESSED: frozenset(
        {"measurement_id", "kind", "method", "reason"}
    ),
    # Lifecycle (state transitions write with no kwargs)
    AuditEventType.SESSION_CREATED: frozenset({"clinician_id", "specialty"}),
    AuditEventType.CONSENT_CONFIRMED: frozenset({"consent_method"}),
    AuditEventType.RECORDING_STARTED: frozenset(),
    AuditEventType.SESSION_PAUSED: frozenset(),
    AuditEventType.STAGE1_STARTED: frozenset(),
    AuditEventType.STAGE1_DELIVERED: frozenset({"stage1_latency_ms"}),
    AuditEventType.STAGE1_EMPTY_NOTE: frozenset(
        {"segment_count", "transcript_char_count", "completeness"}
    ),
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
    # Custom-template lifecycle — never carry the template body/sections
    # (clinician-authored prose we wouldn't want quoted in an audit query).
    # template_id + template_key + actor is enough to reconstruct the change.
    AuditEventType.CUSTOM_TEMPLATE_CREATED: frozenset(
        {"actor_id", "template_id", "template_key"}
    ),
    AuditEventType.CUSTOM_TEMPLATE_UPDATED: frozenset(
        {"actor_id", "template_id", "template_key"}
    ),
    AuditEventType.CUSTOM_TEMPLATE_DELETED: frozenset(
        {"actor_id", "template_id", "template_key"}
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
    AuditEventType.ADMIN_SESSION_DELETED: frozenset({"prior_state", "target_clinician_id"}),
    # Notes / review
    AuditEventType.STAGE1_APPROVED: frozenset(
        {"version", "provider_used", "completeness_score"}
    ),
    AuditEventType.STAGE1_FAILED: frozenset({"reason"}),
    # Stage 1 entry guards. ``reason`` is a bounded enum string
    # ("transcript_empty_or_missing" / "transcript_too_short"), not
    # free text — see ``MIN_TRANSCRIPT_CHAR_THRESHOLD`` in
    # ``modules/note_gen/service.py``. ``transcript_char_count`` on
    # the low-transcript branch is a small integer carrying NO transcript
    # content — only the cumulative char count of all segments. Strictly
    # PHI-safe; the actual segment text never leaves the request scope.
    AuditEventType.STAGE1_SKIPPED_NO_TRANSCRIPT: frozenset({"reason"}),
    AuditEventType.STAGE1_SKIPPED_LOW_TRANSCRIPT: frozenset(
        {"reason", "transcript_char_count"}
    ),
    # Session-stats recompute audit. ``sections_populated`` /
    # ``sections_required`` / ``completeness_score`` are the post-
    # recompute roll-up; they're identical to what the admin endpoints
    # surface so a compliance check can diff "what the dashboard said"
    # against "what the audit row recorded". No PHI — counts only.
    AuditEventType.SESSION_STATS_RECOMPUTED: frozenset(
        {
            "trigger",
            "sections_populated",
            "sections_required",
            "completeness_score",
        }
    ),
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
    # Count-only — no kwargs (never the context id / template / label).
    AuditEventType.SESSION_TEMPLATE_KEY_COERCED: frozenset(),
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
    # iOS-emitted masking FAILURE provenance (AUR-API-CLIENT-AUDIT). All
    # fields are PHI-free: ``frame_type`` ∈ {video, screen, clip};
    # ``failure_reason`` is a bounded enum (MaskingFailureReason on iOS —
    # invalid_image / detection_error / render_error / ocr_error); the
    # remaining fields are integer counts. NEVER an image, S3 key, or body.
    AuditEventType.MASKING_FAILED: frozenset(
        {
            "frame_type",
            "failure_reason",
            "faces_detected",
            "phi_regions_redacted",
            "frames_total",
            "frames_with_faces",
            "frames_failed",
        }
    ),
    # Post-session quarantine resolution — count-only.
    AuditEventType.MASKING_FAILURE_RETRIED: frozenset({"frame_count"}),
    AuditEventType.MASKING_FAILURE_SKIPPED: frozenset({"frame_count"}),
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
            # #324 — clip provenance: "trigger" (spoken-keyword anchored)
            # or "cadence" (during-recording cadence floor for silent
            # exams). A two-value enum, never PHI; count-only telemetry.
            "source",
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
    # Clip drop-site telemetry (#390). PHI-free: a drop-reason enum, an
    # origin ("ios" | "server"), and an optional trigger-anchor timestamp.
    AuditEventType.CLIP_DROPPED: frozenset({"reason", "origin", "timestamp_ms"}),
    # Per-session clip-pipeline counters, flushed by iOS on stop. Flat
    # per-reason drop counts (rather than a nested map) keep the row
    # greppable + the whitelist exhaustive. All counts, never PHI.
    AuditEventType.CLIP_PIPELINE_SUMMARY: frozenset(
        {
            "origin",
            "ring_frames_appended",
            "clips_extracted",
            "clips_masked",
            "clips_uploaded",
            "clips_dropped",
            "drops_ring_empty",
            "drops_masking_failed",
            "drops_upload_failed",
        }
    ),
    # Resolved clip config + app build captured at record-start. The
    # mode/cadence/fps are non-PHI tuning values; app_build is the client
    # version string. No identifiers.
    AuditEventType.CLIP_CONFIG_SNAPSHOT: frozenset(
        {
            "origin",
            "visual_evidence_mode",
            "clip_cadence_seconds",
            "video_capture_fps",
            "clip_window_ms",
            "app_build",
        }
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
    # Cleanup.
    # AUDIO_PURGED carries EITHER a single ``s3_key`` (the legacy
    # key-scoped `purge_audio`) OR an ``audio_count`` (the prefix-based
    # `purge_audio_for_session` added for #338, which deletes every
    # `audio/{session_id}/...` object and has no single canonical key).
    # Widening a whitelist is back-compatible — existing consumers keep
    # working; the count is PHI-free (an integer, never an object body).
    AuditEventType.AUDIO_PURGED: frozenset({"bucket", "s3_key", "audio_count"}),
    AuditEventType.FRAMES_PURGED: frozenset({"bucket", "frame_count"}),
    AuditEventType.EVAL_FRAMES_MIGRATED: frozenset(
        {"source_bucket", "dest_bucket", "frame_count"}
    ),
    AuditEventType.CLEANUP_PARTIAL_FAILURE: frozenset(
        {"bucket", "s3_key", "error_message", "failed_count"}
    ),
    # Windowed media retention (#338) — a reviewer minted a replay URL for
    # retained media. ``actor_id`` is the requester UUID; ``evidence_kind``
    # is one of {"audio", "clip", "frame"}; ``ttl_seconds`` is the signed-
    # URL validity window. NEVER the S3 key, the signed URL, or any body —
    # the row records THAT replay happened, not WHAT was replayed.
    AuditEventType.EVIDENCE_REPLAYED: frozenset(
        {"actor_id", "evidence_kind", "ttl_seconds"}
    ),
    # Windowed media retention (#338) — an ADMIN/EVAL_TEAM reviewer minted
    # download URLs for a session's retained media via the admin Captured
    # Media page. ``actor_id`` is the requester UUID; ``evidence_kind`` is
    # the fixed string "session_media"; ``audio_count`` / ``clip_count`` are
    # the PHI-free object counts the call presigned. NEVER an S3 key, the
    # signed URL, or any body — the row records THAT a download happened and
    # how many objects, not WHAT was downloaded.
    AuditEventType.EVIDENCE_DOWNLOADED: frozenset(
        {"actor_id", "evidence_kind", "audio_count", "clip_count"}
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
            "deleted_transcripts",
            "deleted_s3_objects",
            "retention_note",
        }
    ),
    # Profile (#260) — team list edit. NEVER include the names
    # themselves; the count delta is the only audit-trail-meaningful
    # signal we want in the immutable row.
    AuditEventType.TEAM_MEMBERS_UPDATED: frozenset(
        {"actor_id", "members_count_before", "members_count_after"}
    ),
    # Profile (#259) — consultation-types list edit. NEVER include the
    # type strings themselves. The deltas are split into
    # defaults/customs so the post-pilot review can answer "did
    # clinicians actually use the custom-types feature?" without
    # surfacing any labels.
    AuditEventType.PROFILE_CONSULTATION_TYPES_UPDATED: frozenset(
        {
            "actor_id",
            "count_before",
            "count_after",
            "defaults_added",
            "defaults_removed",
            "customs_added",
            "customs_removed",
        }
    ),
    # Profile (#313, B1) — visit-type → context → template map edit. The
    # whitelist is AGGREGATE COUNTS ONLY. NEVER include the context
    # labels, the visit-type keys, the context ids, or the attached
    # template keys — all are user-authored and PHI-risk. ``actor_id`` is
    # the clinician UUID; the five count fields let the post-pilot review
    # answer "did clinicians adopt contexts/templates?" without surfacing
    # any free text.
    AuditEventType.PROFILE_CONTEXTS_UPDATED: frozenset(
        {
            "actor_id",
            "visit_types_touched",
            "contexts_added",
            "contexts_removed",
            "templates_attached",
            "templates_detached",
            # #318 / B3 — count-only custom-template binding churn. Same
            # PHI posture as the built-in pair above: no ids, no refs, no
            # template names — just how many contexts gained / lost a
            # custom template_ref.
            "custom_templates_attached",
            "custom_templates_detached",
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
    # Card-visibility feature flag update (lane-full/card-visibility-flags).
    # ``changed_by`` is the ADMIN's UUID; ``changed_fields`` is a sorted
    # list of the flag NAMES that flipped (e.g. ``["orders_card_enabled"]``);
    # ``appconfig_version`` is the new hosted-version number returned by
    # ``appconfig.create_hosted_configuration_version``. The flag VALUES
    # are deliberately NOT in the audit row — they're config, not PHI, and
    # AppConfig already versions them independently.
    AuditEventType.FEATURE_FLAGS_UPDATED: frozenset(
        {"changed_by", "changed_fields", "appconfig_version"}
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
    # count). The user prompt TEXT itself is deliberately excluded —
    # it's personal phrasing the physician wouldn't want quoted in an
    # audit query, and the length is sufficient for the "did anything
    # change?" audit story. CLEARED doesn't carry user_prompt_length
    # (it's zero by definition) — the actor_id + prompt_id pair is
    # enough.
    AuditEventType.PROMPT_USER_PROMPT_SET: frozenset(
        {"actor_id", "prompt_id", "user_prompt_length"}
    ),
    AuditEventType.PROMPT_USER_PROMPT_CLEARED: frozenset(
        {"actor_id", "prompt_id"}
    ),
    # Prompt Studio publish — provenance only, never the prompt text.
    # target_role rides only on ROLE-scoped publications.
    AuditEventType.PROMPT_STUDIO_PUBLISHED: frozenset(
        {"actor_id", "job_id", "version_no", "scope", "target_role"}
    ),
    # Longitudinal patient context loaded into Stage 1 note generation
    # (#61, full slice). The whitelist is the entire PHI-safety
    # contract for this event — adding a key here is a deliberate
    # security decision, not an incidental refactor.
    #   * actor_id              — clinician_id of the session owner.
    #   * current_session_id    — anchor row for the Stage 1 call.
    #   * encounters_count      — integer count of prior encounters
    #                              the LLM prompt actually consumed.
    #   * last_encounter_date   — ISO date of the most recent prior
    #                              visit. Calendar-grain only, never
    #                              the timestamp; date alone is the
    #                              minimum signal pilot analysis
    #                              needs and avoids re-encoding when
    #                              prior context fired.
    # NO identifier value. NO prior session ids. NO clinical content.
    AuditEventType.LONGITUDINAL_CONTEXT_LOADED: frozenset(
        {
            "actor_id",
            "current_session_id",
            "encounters_count",
            "last_encounter_date",
        }
    ),
    # ── Auth pivot ────────────────────────────────────────────────────────
    # Email NEVER appears in any of these whitelists — only UUIDs. The
    # ``reason`` strings are bounded enums (see auth router), not free
    # text. ``token_id`` is the UUID of the refresh_tokens row, never
    # the raw token. ``via`` distinguishes self-reset from admin-reset
    # for the post-pilot security review.
    AuditEventType.LOGIN_SUCCESS: frozenset({"actor_id"}),
    AuditEventType.LOGIN_FAILURE: frozenset({"target_user_id", "reason"}),
    AuditEventType.LOGIN_LOCKED: frozenset(
        {"target_user_id", "failed_count"}
    ),
    AuditEventType.LOGOUT: frozenset({"actor_id"}),
    AuditEventType.MFA_ENROLLED: frozenset({"actor_id"}),
    AuditEventType.MFA_RESET: frozenset({"actor_id", "target_user_id"}),
    AuditEventType.MFA_DISABLED: frozenset({"actor_id"}),
    AuditEventType.SESSION_REVOKED: frozenset({"actor_id", "token_id"}),
    AuditEventType.SESSIONS_REVOKED_ALL: frozenset({"actor_id", "count"}),
    AuditEventType.PASSWORD_RESET_REQUESTED: frozenset({"target_user_id"}),
    AuditEventType.PASSWORD_CHANGED: frozenset({"actor_id", "via"}),
    AuditEventType.ADMIN_PASSWORD_RESET_ISSUED: frozenset(
        {"actor_id", "target_user_id"}
    ),
    AuditEventType.REFRESH_TOKEN_ISSUED: frozenset({"actor_id", "token_id"}),
    AuditEventType.REFRESH_TOKEN_ROTATED: frozenset(
        {"actor_id", "previous_token_id", "new_token_id"}
    ),
    AuditEventType.REFRESH_TOKEN_REVOKED: frozenset(
        {"actor_id", "token_id", "reason"}
    ),
    # ── Web-portal video import (VID-01…) — all PHI-free ──────────────────
    AuditEventType.VIDEO_IMPORT_STARTED: frozenset({"actor_id"}),
    AuditEventType.VIDEO_IMPORT_COMPLETE: frozenset(
        {"frames_extracted", "frames_masked", "frames_dropped"}
    ),
    AuditEventType.VIDEO_IMPORT_FAILED: frozenset({"reason"}),
    AuditEventType.CONSENT_ATTESTED: frozenset({"actor_id", "method"}),
    # Raw uploaded video purged after audio/frame extraction. Bucket + key
    # only (the key is `video-imports/{session_id}/{uuid}.mp4` — session
    # UUID, not PHI), never a body. Failure reuses CLEANUP_PARTIAL_FAILURE.
    AuditEventType.RAW_VIDEO_PURGED: frozenset({"bucket", "s3_key"}),
    # Server-side masking (VID-04). Counts + timestamp only — NEVER an image,
    # an S3 key, or a body. `reason` on _FAILED is a bounded enum string
    # (e.g. "no_face_detected", "decode_error").
    AuditEventType.SERVER_MASKING_APPLIED: frozenset(
        {"timestamp_ms", "faces_detected", "faces_blurred"}
    ),
    AuditEventType.SERVER_MASKING_FAILED: frozenset({"timestamp_ms", "reason"}),
}


# ── Client-origin audit allow-list (AUR-API-CLIENT-AUDIT) ─────────────────
#
# The set of event types iOS is permitted to POST to
# ``/sessions/{id}/client-audit-events``. Deliberately NARROW: only events
# the device is the sole authority for AND the server doesn't already emit
# from the matching API call. This doubles as a de-dup guard — server-
# authoritative events (consent_confirmed, login_success, frame_uploaded, …)
# are NOT here, so a client can neither forge nor duplicate them.
#
# Scoped to the masking FAILURE family: a dropped frame never uploads, so
# these are the one masking signal with no server-side equivalent. (Masking
# of UPLOADED media is already audited via FRAME_UPLOADED / CLIP_UPLOADED /
# SCREEN_FRAME_PROCESSED, which carry the same proof fields.)
CLIENT_AUDIT_EVENTS: frozenset[AuditEventType] = frozenset(
    {
        AuditEventType.MASKING_FAILED,
        AuditEventType.MASKING_FAILURE_RETRIED,
        AuditEventType.MASKING_FAILURE_SKIPPED,
    }
)


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

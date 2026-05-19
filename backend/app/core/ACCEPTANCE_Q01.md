# Q-01 — AuditEventType StrEnum (Acceptance Criteria)

## Goal

Replace ~30 untyped `event_type="..."` string literals scattered
through route handlers + service modules with a single typed
`AuditEventType` StrEnum. Audit emissions stay
wire-format-identical — every member's `value` is the exact string
already written to DynamoDB — but the call sites become greppable and
typo-proof.

## Out of scope

- Per-event kwarg whitelisting. That's Q-03 (depends on this PR).
- The TypedDict layer on `write_audit(**fields)` — Q-03 again.
- Renaming existing string values. Backwards compatibility with
  historical audit rows is non-negotiable; rename = breaking change.

## Approach

1. New file: `backend/app/core/audit_events.py`
   - `class AuditEventType(StrEnum)` with every known event type as a
     member. Subclassing `str` (via `StrEnum`) means `event_type=...`
     receives an enum value that the audit log serializes byte-for-byte
     the same as the old literal.
   - Members grouped by domain (lifecycle, notes, frames, screen,
     transcription, vision, cleanup, account, admin, system).
   - Module docstring explicitly forbids changing a member's `.value`
     once it's been written to DynamoDB.

2. Update `app/api/v1/_helpers.write_audit` signature:
   ```python
   async def write_audit(
       session_id: str | uuid.UUID,
       event_type: AuditEventType | str,
       **fields: Any,
   ) -> None: ...
   ```
   Accepting `str` keeps the door open for data-driven sites (e.g.
   `get_audit_event_for_state` returning a fallback string for unknown
   states); the StrEnum is the normalized path.

3. Update `app.modules.session.service.STATE_AUDIT_EVENTS` map type to
   `dict[SessionState, AuditEventType]`. The fallback in
   `get_audit_event_for_state` stays as a raw `str` — it's a guard
   for a SessionState added without updating the map and only fires
   in development.

4. Sweep every `write_audit(..., "literal", ...)` and
   `audit.write_event(..., event_type="literal", ...)` callsite to use
   `AuditEventType.LITERAL`. Run grep to confirm zero residual matches.

## Membership

Drawn from the full survey of `app/`. Members listed in PR commit
to make code review straightforward; production audit rows already
use these strings.

### Lifecycle (state transitions)
session_created, consent_confirmed, recording_started,
session_paused, stage1_started, stage1_delivered, stage2_started,
full_note_delivered, note_exported, session_purged

### Notes
stage1_approved, stage1_failed, stage2_skipped, stage2_complete,
stage2_failed, note_version_created, template_changed

### Frames / masking
frame_uploaded, screen_frame_processed, masking_confirmed

### Transcription
transcription_complete, transcription_failed, s3_upload_failed

### Vision
vision_frame_failed, provider_fallback

### Cleanup
audio_purged, frames_purged, eval_frames_migrated,
cleanup_partial_failure

### Privacy / account
biometric_consent_confirmed, voice_enrollment_complete,
voice_enrollment_deleted, account_deleted

### Admin
user_created, user_updated, eval_score_submitted

### System
config_changed, provider_changed

## Files touched

- **New:** `backend/app/core/audit_events.py`
- `backend/app/api/v1/_helpers.py`
- `backend/app/api/v1/sessions.py`
- `backend/app/api/v1/notes.py`
- `backend/app/api/v1/frames.py`
- `backend/app/api/v1/screen.py`
- `backend/app/api/v1/transcription.py`
- `backend/app/api/v1/vision.py`
- `backend/app/api/v1/privacy.py`
- `backend/app/api/v1/export.py`
- `backend/app/api/v1/admin/users.py`
- `backend/app/api/v1/admin/eval.py`
- `backend/app/modules/transcription/service.py`
- `backend/app/modules/vision/service.py`
- `backend/app/modules/cleanup/service.py`
- `backend/app/modules/export/service.py`
- `backend/app/modules/session/service.py`
- **New:** `backend/tests/unit/test_audit_events.py`

## DRY / SOLID gates

- **DRY:** every event type defined exactly once, in
  `audit_events.py`. The compliance-officer-readable inventory lives
  in the source file — no duplication into docs.
- **SRP:** the enum has one job (catalog audit event types). It does
  not carry per-event metadata (allowed fields, retention, etc.); that
  belongs to Q-03's TypedDict layer.
- **OCP:** new event types are added by appending a member, not
  editing existing ones. The regression test asserts every existing
  member's value is unchanged.
- **DIP:** `write_audit` accepts the enum *or* a raw string. Callers
  pass the enum by default; the fallback path in
  `get_audit_event_for_state` returns `str` for unknown states without
  needing a special "unknown" enum member.

## Acceptance

```bash
grep -rn 'write_audit(.*,\s*"[a-z_]\+"' backend/app  # → 0
grep -rn 'event_type="[a-z_]\+"' backend/app          # → 0
                                                       # (admin write-through routes
                                                       # that read events from
                                                       # DynamoDB are exempt — they
                                                       # consume, not emit.)
pytest backend -q                                      # → 228 passing (225 + 3 new)
```

## Risk + mitigation

- **Wire-format drift:** if a member's `.value` differs by a character,
  historical audit queries break. Regression test
  `test_audit_event_type_values_locked` asserts the full
  `{member: value}` map against a hard-coded expected dict.
- **Missed callsite:** grep-based sweep is the safety net. The post-PR
  acceptance grep returns 0.
- **Import cycles:** `audit_events.py` lives in `core/` and has no
  dependencies on modules/ or api/. Routes import from core; the
  reverse is forbidden by the module isolation rule in CLAUDE.md.

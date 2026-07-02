# Plan — #605 Raw Data Purge timing (hybrid: spec-by-default, replay opt-in)

## Task
Close the purge-timing gap vs the MVP Scope Definition ("audio deleted <1hr
post-transcription; video purged 24hr post-export; confirmed in the immutable
audit log") **without breaking** the shipped windowed-media-retention replay
feature (#338).

**Decision (2026-07-01): Hybrid.** Tie in-band purge to the existing
`media_review_retention_enabled` feature flag:
- **Flag OFF (prod default) → spec-strict.** Raw audio is purged **in-band right
  after Stage-1 transcription** (<1hr); frames/clips are purged **on export**
  (immediate — stricter than the 24hr spec). The S3 lifecycle TTL
  (`media_retention_days`, prod = 1 day) remains the timed backstop.
- **Flag ON (dev) → keep-window.** Audio + frames/clips are retained for the
  review/replay window so the clinician (and admin) can replay/download the
  encounter media (#338); the S3 lifecycle TTL is the max-window backstop. No
  in-band purge runs.

## Why
Audit finding: the purge **machinery + immutable audit logging are fully wired
and verified**, but the timing guarantees are not enforced in-band —
- audio is never purged after transcription (only the whole-day S3 lifecycle
  deletes it), and
- `variables.tf` carries a **stale comment** claiming an "app-level
  purge-on-approval that removes raw audio right after transcription" that was
  never wired.

The keep-window model (#338) was a deliberate shift for audio replay, so we
can't just purge unconditionally — hence the flag-gated hybrid.

## Approach
1. **In-band audio purge** — `api/v1/transcription.py::run_stage1`: after the
   transcript row is persisted (`db.flush()`), if
   `not get_config().feature_flags.media_review_retention_enabled`, call
   `cleanup.purge_audio_for_session(str(session_id))` (the already-wired,
   prefix-based purge that emits `AUDIO_PURGED`). **Fail-soft** — wrapped in
   try/except so a purge hiccup never fails a delivered note; the S3 lifecycle
   backstops it. Placed after transcript persist so the derived transcript is
   safely stored before the raw audio goes. Covers BOTH callers of `run_stage1`
   (iOS `/stop` and the web-portal video-import orchestrator).
2. **Video purge stays flag-gated on export** — `export/service.py::
   export_note_docx`: gate the existing `purge_frames` / `purge_clips` calls on
   `not media_review_retention_enabled`. Flag OFF (prod) → purge immediately, as
   today (no prod behaviour change). Flag ON (dev) → skip, keeping frames/clips
   for the replay window. Eval-frame/clip migration is unchanged (runs
   regardless — the eval bucket has its own retention regime).
3. **No new scheduler for the "24hr sweep."** The app has no cron; immediate-on-
   export (flag OFF) is stricter than 24hr, and the S3 lifecycle TTL is the
   timed backstop for the flag-ON / never-exported cases. Documented, not built.
4. **Fix the stale `infrastructure/variables.tf` comment** to describe the
   actually-wired behaviour (flag-gated in-band audio-after-transcription +
   frames/clips-on-export; lifecycle as backstop).

## Acceptance criteria
- [ ] AC-1: With `media_review_retention_enabled` **False**, `run_stage1` awaits
  `purge_audio_for_session(session_id)` after a successful transcription.
- [ ] AC-2: With the flag **True**, `run_stage1` does **not** purge audio (kept
  for replay).
- [ ] AC-3: The audio purge is **fail-soft** — a raising `purge_audio_for_session`
  does not fail `run_stage1` (the transcript is still returned / note delivered).
- [ ] AC-4: With the flag **False**, `export_note_docx` awaits `purge_frames` +
  `purge_clips` (unchanged prod behaviour).
- [ ] AC-5: With the flag **True**, `export_note_docx` does **not** purge
  frames/clips (kept for the window); eval migration still runs.
- [ ] AC-6: `variables.tf` comment reflects the wired behaviour (no stale
  "purge-on-approval" claim).

## DRY / SOLID
- Reuses the already-wired `purge_audio_for_session`, `purge_frames`,
  `purge_clips` (which each emit their own audit rows) and the single
  `media_review_retention_enabled` flag — no new purge code, no new flag, no
  scheduler. One shared runtime read (`get_config().feature_flags...`).

## Security implications
- Tightens PHI handling: raw audio (PHI) is deleted in-band <1hr post-
  transcription in the default (flag-OFF) posture instead of lingering up to the
  whole-day lifecycle. Every purge still writes an immutable, PHI-free audit row
  (`AUDIO_PURGED`/`FRAMES_PURGED` carry only bucket + count). Replay retention
  stays strictly opt-in behind the compliance-gated flag. No prompt, no audit-
  schema, no new PHI path.

## Out of scope
No new scheduler / timed sweep. No change to eval-frame migration, the audit
schema, note flow, or the retention flag's other surfaces (replay/download).
The S3 lifecycle TTL values (`media_retention_days`) are unchanged.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_raw_data_purge_timing.py -q`
   (flag-OFF purges audio + video; flag-ON keeps both; audio purge fail-soft).
2. Regression: `python3 -m pytest tests/unit/test_cleanup.py tests/unit/test_stage1_empty_transcript_guard.py tests/unit/test_video_import_orchestrator.py -q`.
3. `ruff check` changed files; `terraform fmt -check variables.tf`.

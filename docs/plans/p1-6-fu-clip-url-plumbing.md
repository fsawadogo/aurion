# P1-6-FU — Signed clip URL through `GET /notes/full` + `GET /notes/detail`

**Canonical plan:** [`/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`](../../../../.claude/plans/dual-mode-visual-evidence.md)
(Phase 1, follow-up to the iOS-side P1-6 PR #204.)

**Type:** backend-only follow-up. No iOS work in this PR — the iOS decoder
(`NoteClaimResponse`) already carries `evidenceKind`, `durationMs`, and
`clipURL`, defaulting to `.frame` / `nil` so the wire shape is
byte-compatible. This PR populates those fields server-side.

## Why

iOS reviewers see a play-triangle indicator on `CitationChip` for visual
claims whose backing evidence is a `clip`. Tapping the chip opens
`FullClipView`, which calls `AurionVideoPlayer(url:)` on the claim's
`clipURL`. Today, every visual citation's `clipURL` decodes as `nil` —
the backend's `NoteClaimResponse` schema doesn't carry the field — so
tap shows the localized "clip not yet available" alert instead of the
player. iOS has been waiting for this server surface since PR #204
landed.

## Scope

1. Extend `NoteClaimResponse` (and `CitationExpansion`) with three additive
   optional fields:
   - `evidence_kind: Literal["frame", "clip"] | None` — `None` for non-visual
     sources; `"frame"` or `"clip"` for visual sources.
   - `duration_ms: int | None` — clip window length in ms; populated only for
     clip-kind.
   - `clip_url: str | None` — short-TTL signed S3 URL for direct playback;
     populated only for clip-kind.
2. New `core/s3.py::generate_presigned_evidence_url(s3_key, ttl_seconds=3600)`
   — single source of truth for evidence presign. Used by both the
   `NoteClaimResponse` builder (`_to_note_response`) and the `CitationExpansion`
   builder (`_expand_claim`) so we never have two slightly-different presign
   call sites.
3. Detect clip-kind by `claim.source_type == "visual"` AND
   `claim.source_id.endswith("_clip")` — the source_id convention from
   `caption_clip` in `providers/vision/gemini.py:188`
   (`frame_id=f"{clip.trigger_segment_id}_clip"`). Frame-kind visual claims
   carry `source_id="frame_NNNNN"`.
4. Resolve the S3 key once per request via a memoized resolver that lists
   `clips/{session_id}/` in S3. One LIST per request, regardless of how
   many clip-kind claims the note carries (DRY).
5. PHI scan: AST-walk every logger call in `core/s3.py` and the touched
   note-builder functions, assert no full `s3_key`, no full signed URL, no
   transcript content. Truncate to 12 chars in log lines.

## Out of scope

- Frame-kind URLs. The reviewer doesn't currently fetch frame stills via a
  signed URL (it falls back to `frame_s3_key` metadata; the still itself
  isn't displayed in the iOS chip path). Frame URL plumbing lands as a
  separate follow-up if needed.
- Audit events for each URL fetch — too noisy. Only state-changing
  operations get audit rows; URL fetch is per-request and ephemeral.
- New upload paths. We're exposing already-masked already-uploaded clips.
- iOS work. The decoder is already in `NoteClaimResponse`
  (`APIClient.swift:1096-1170`).

## Acceptance criteria

- [ ] AC-1: A clip-kind visual claim in `GET /notes/{id}/full` carries
      `evidence_kind="clip"`, `duration_ms=<int>`, `clip_url=<signed URL>`,
      where the URL matches `^https://.*\.amazonaws\.com/.*\?.*X-Amz-Signature=.*`.
- [ ] AC-2: A frame-kind visual claim carries `evidence_kind="frame"`,
      `duration_ms=null`, `clip_url=null`.
- [ ] AC-3: A non-visual claim (`transcript`, `screen`, `physician_edit`)
      carries `evidence_kind=null`, `duration_ms=null`, `clip_url=null`.
- [ ] AC-4: Signed URL TTL is exactly 3600s (mock the signing client,
      assert the `ExpiresIn` param).
- [ ] AC-5: Two parallel claims with clip-kind backing in the same note
      response trigger exactly ONE S3 LIST call (per-request memoization).
- [ ] AC-6: `GET /notes/{id}/detail::citations[claim_id]` carries the same
      three fields with the same population rules (parity with `full`).
- [ ] AC-7: `test_no_phi_in_clip_url_log_statements` — AST-walks every
      logger call in `core/s3.py` and asserts no full session_id / no full
      s3_key / no signed URL is emitted.
- [ ] AC-8: Full backend suite `pytest -q` passes (baseline 775).

## DRY / SOLID check

- **Existing helpers to reuse:** `get_s3_client()` (`core/s3.py`),
  `FRAMES_BUCKET` (`core/s3.py`), the note builder switch in
  `_expand_claim` (`api/v1/notes.py`).
- **New helper introduced?** Yes — `generate_presigned_evidence_url`.
  This is the THIRD copy of the pattern only if we count two callers
  in this PR; it's introduced because both the wire `NoteClaimResponse`
  builder AND the web `CitationExpansion` builder need to presign for
  the same evidence, and copy-pasting `boto3.generate_presigned_url`
  kwargs into two call sites is exactly the DRY violation the workflow
  rejects.
- **SRP:** the helper signs. The note builder fetches + composes. The
  per-request resolver caches. Three separate functions, three single
  responsibilities.
- **OCP:** `evidence_kind` field is additive. The claim builder branches
  once on `source_type == "visual"`, then once on the source_id suffix.
  Two switches, no chain of nested ifs.
- **LSP:** `evidence_kind` carries the same semantic across `FrameCaption`
  (P1-1), `NoteClaimResponse`, and `CitationExpansion`. iOS + web both
  read the same shape.
- **DIP:** S3 client via `get_s3_client()`; presign via the new helper.
  No direct `boto3.client("s3")` calls.

## Files touched

- `backend/app/core/s3.py` — add `generate_presigned_evidence_url`.
- `backend/app/api/v1/notes.py` — extend `NoteClaimResponse`,
  `CitationExpansion`, `_to_note_response`, `_expand_claim`. Add per-request
  clip-key resolver.
- `backend/tests/integration/test_note_response_clip_urls.py` — new file
  covering every AC above.
- `docs/plans/p1-6-fu-clip-url-plumbing.md` — this file.

## Security implications

- Signed URLs reuse the existing KMS-encrypted S3 bucket — the SignatureV4
  authentication includes the KMS-decrypt permission via the IAM role; no
  new bucket / no new policy.
- TTL of 3600s is long enough for a review session, short enough that a
  screenshot of the URL becomes useless before exploitation.
- The signed URL itself contains the S3 key (which contains the
  session_id). Session IDs are UUIDs, not PHI per Aurion's classification.
  But explicit PHI scan asserts no log line emits the full URL or the
  full S3 key.
- No new upload path → fail-closed masking gate (P0-01) is untouched.
- No new audit event types — URL fetch is per-request and ephemeral.
- Owner assertion stays at the endpoint boundary
  (`get_owned_session_or_404`) — non-owners never reach `_to_note_response`.

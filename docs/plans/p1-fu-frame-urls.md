# P1-FU-FRAME-URLS — Signed frame URL through `GET /notes/full` + `GET /notes/detail`

**Canonical plan:** [`/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`](../../../../.claude/plans/dual-mode-visual-evidence.md)
(Phase 1 follow-up — symmetry with P1-6-FU which plumbed clip URLs.)

**Type:** backend-only follow-up. No iOS work in this PR — the existing
iOS decoder defaults the new optional field to nil and falls back to its
on-device frame cache.

## Why

P1-6-FU closed the clip side: every clip-kind visual claim now carries a
signed S3 URL (`clip_url`) so the iOS reviewer + web review UI can play
the masked clip inline. Frame-kind visual claims still have NO
server-side signed URL — iOS gets away with it today because the device
has the original frame bytes cached locally. That leaves three real
gaps:

- **Reinstalled / fresh iOS device** — frame citations have no fallback
  surface; the chip can't render the still.
- **Web portal compliance officers** — they have no local cache; they
  literally cannot see frames at all when reviewing notes.
- **Eval team running validation on frames_only sessions** — no visual
  verification of what the vision model described.

This PR closes the symmetry. After it lands, frame-kind visual claims
carry `frame_url=<signed S3 URL>` the same way clip-kind claims carry
`clip_url`.

## Scope

1. Extend `NoteClaimResponse` and `CitationExpansion` with one additive
   optional field:
   - `frame_url: str | None` — short-TTL signed S3 URL for the masked
     frame still. Populated only for frame-kind visual claims; `None`
     for clip-kind, non-visual, and any case where signing/listing
     fails (graceful degradation).

2. Reuse the existing `core/s3.py::generate_presigned_evidence_url`
   helper — same TTL (1h), same KMS-via-IAM contract, same PHI-safe
   logging convention. The DRY check enforces this: no second presign
   helper.

3. Refactor `_build_clip_url_resolver` → `_build_evidence_url_resolver`.
   The new factory:
   - Memoizes one S3 LIST per request for `frames/{session_id}/` AND one
     for `clips/{session_id}/`. Two LIST calls maximum, regardless of
     how many citations the note carries.
   - Returns a closure `resolve_url(source_id, evidence_kind) -> Optional[str]`
     that routes to the right prefix based on `evidence_kind`.
   - Same 1h TTL for both kinds.
   - Same graceful degradation on LIST or presign failure — return
     `None`, never 500.

4. Update `_to_note_response` / `_claim_to_response` and
   `_build_citations` / `_expand_claim` to call the unified resolver:
   - `source_type != "visual"` → all URL fields stay `None`.
   - `source_type == "visual"` → determine `evidence_kind` from
     `source_id` suffix (same `_clip` marker as P1-6-FU), then:
     - frame-kind → set `frame_url`, leave `clip_url` / `duration_ms` `None`.
     - clip-kind → set `clip_url` + `duration_ms` (existing P1-6-FU
       behaviour, unchanged), leave `frame_url` `None`.

5. Tests (`backend/tests/integration/test_note_response_frame_urls.py`):
   - Mixed-citation note: frame claim → `frame_url=<presigned>` + `clip_url=None`;
     clip claim → `clip_url=<presigned>` + `frame_url=None`; non-visual → all `None`.
   - Frame URL matches the signed-S3 regex.
   - Frame URL TTL is exactly 3600 seconds (assert `ExpiresIn` on the mock).
   - One LIST per kind per request (`call_count == 1` for the frames LIST,
     and `1` for the clips LIST when both kinds appear).
   - Graceful degradation: frames LIST failure → `frame_url=None` but
     `evidence_kind="frame"` preserved.
   - PHI scan: no full S3 keys, no signed URLs, no transcript content
     in any log line across `core/s3.py` and `api/v1/notes.py`.
   - Backward compat: a legacy decoder (no `frame_url` key) still parses
     the response.

## Out of scope

- iOS work. The existing decoder treats `frame_url` as optional; older
  iOS clients ignore it; newer iOS clients can adopt later.
- Audit events for each URL fetch — same call as P1-6-FU: per-request,
  ephemeral, not auditable.
- Screen frames (`screen_NNNNN`) — those follow the screen pipeline, not
  the dual-mode visual evidence pipeline. They keep `frame_url=None`
  (their `frame_s3_key` metadata is enough for the web reviewer).
- New upload paths. We're exposing already-masked already-uploaded frames.

## Acceptance criteria

- [ ] AC-1: A frame-kind visual claim in `GET /notes/{id}/full` carries
      `frame_url=<signed URL>`, `clip_url=None`, `duration_ms=None`,
      `evidence_kind="frame"`. URL matches
      `^https://.*\.amazonaws\.com/.*\?.*X-Amz-Signature=.*`.
- [ ] AC-2: A clip-kind visual claim in `GET /notes/{id}/full` carries
      `frame_url=None`, `clip_url=<signed URL>`, `duration_ms=<int>`,
      `evidence_kind="clip"` — P1-6-FU behaviour preserved.
- [ ] AC-3: Non-visual claims carry `frame_url=None`, `clip_url=None`,
      `duration_ms=None`, `evidence_kind=None`.
- [ ] AC-4: Frame signed-URL TTL is exactly 3600s (mock the signing
      client, assert `ExpiresIn`).
- [ ] AC-5: Two frame-kind claims in the same response trigger exactly
      ONE `list_objects_v2` call for `frames/{session_id}/`. If clip-kind
      claims are also present, ONE separate LIST for `clips/{session_id}/`
      fires. Total LIST calls = #distinct prefixes touched, not #claims.
- [ ] AC-6: `GET /notes/{id}/detail::citations[claim_id]` carries
      `frame_url` with the same population rules as `/full` — parity.
- [ ] AC-7: PHI scan — AST-walks every logger call in `core/s3.py` and
      `api/v1/notes.py`, asserts no full s3 key / signed URL / PHI var
      lands in a log line.
- [ ] AC-8: Frames LIST failure → `frame_url=None` but
      `evidence_kind="frame"` preserved (response still 200).
- [ ] AC-9: Legacy decoder (ignores `frame_url`) parses the new payload
      and a payload missing `frame_url` decodes (Pydantic default).
- [ ] AC-10: Existing P1-6-FU clip-URL tests
      (`test_note_response_clip_urls.py`) ALL still pass — the resolver
      refactor is byte-compatible on the clip path.
- [ ] AC-11: Full backend suite `pytest -q` passes (baseline 831).

## DRY / SOLID check

- **Existing helpers to reuse:** `get_s3_client()` (`core/s3.py`),
  `FRAMES_BUCKET` (`core/s3.py`), `generate_presigned_evidence_url`
  (`core/s3.py`, added in P1-6-FU), the existing `_is_clip_kind_source_id`
  helper.
- **New helper introduced?** No new presign helper — DRY check enforced
  by grep. The clip-only resolver factory is renamed and broadened to
  cover both kinds; the public contract changes from "clip URL
  resolver" to "evidence URL resolver" but `_to_note_response` /
  `_expand_claim` call patterns stay identical (one closure, one
  source_id per claim).
- **SRP:** the resolver factory does ONE thing — given a session_id,
  produce a closure that maps `(source_id, evidence_kind)` to an
  Optional URL. The claim builder fetches metadata + composes. The
  presign helper signs. Three single responsibilities, three functions.
- **OCP:** `frame_url` is additive. The closure branches on
  `evidence_kind` (which is itself a closed enum: `frame | clip`). No
  new `if provider == ...` style chains.
- **LSP:** `frame_url` mirrors `clip_url` shape — both `Optional[str]`,
  both populated via the same helper, both treated identically on the
  web + iOS decoder side (optional URL → graceful fallback).
- **DIP:** S3 client via `get_s3_client()`; presign via the existing
  helper. No direct `boto3.client("s3")` calls.

## Files touched

- `backend/app/api/v1/notes.py` — extend `NoteClaimResponse`,
  `CitationExpansion`, `_to_note_response`, `_claim_to_response`,
  `_expand_claim`. Refactor `_build_clip_url_resolver` →
  `_build_evidence_url_resolver` with frames LIST memoization added
  alongside the existing clips LIST.
- `backend/tests/integration/test_note_response_frame_urls.py` — new file
  covering every AC above.
- `docs/plans/p1-fu-frame-urls.md` — this file.

## Security implications

- Signed URLs reuse the existing KMS-encrypted S3 bucket — the SignatureV4
  authentication includes the KMS-decrypt permission via the IAM role; no
  new bucket / no new policy.
- TTL of 3600s is consistent with `clip_url` — long enough for a review
  session, short enough that a screenshot of the URL becomes useless
  before exploitation.
- The signed URL contains the S3 key (which contains the session_id).
  Session IDs are UUIDs, not PHI per Aurion's classification. PHI scan
  asserts no log line emits the full URL or the full S3 key.
- No new upload path → fail-closed masking gate (P0-01) is untouched.
- No new audit event types — URL fetch is per-request and ephemeral.
- Owner assertion stays at the endpoint boundary
  (`get_owned_session_or_404`) — non-owners never reach the resolver.

# P1-FU-GEMINI-PROBE — Admin vision-clip probe endpoint

**Canonical plan reference:** Phase 1 dual-mode visual evidence — gap audit
on the Gemini end-to-end path.

**Type:** backend-only follow-up. Adds a single new admin diagnostic
endpoint plus a bundled test fixture and operator doc. No iOS work.
No new migration. Additive only.

## Task

P1-FU-GEMINI-PROBE — operator-only diagnostic that exercises
`VisionProvider.caption_clip` end-to-end against the configured
`vision_clip` provider (default Gemini 2.5 Pro) without persisting
anything to S3, the session table, or the note. Returns a structured
diagnostic with provider, model id, latency, success/failure, the
caption (on success), and a safe error message (on failure).

## Why

Phase 1 shipped a complete code path from iOS recording →
`/clips/{session_id}` → Stage 2 dispatch → `caption_clip` → citation.
But the Gemini path has **never been called end-to-end with real
credentials**. Every existing test mocks the Files API and
`generateContent`. We don't actually know:

* whether the `GOOGLE_AI_API_KEY` secret is set in the dev environment
  (today the provider reads `os.getenv("GOOGLE_AI_API_KEY")` at import
  time and throws `ProviderError` if missing — we only discover that
  when a real session fires);
* whether `gemini.py:caption_clip`'s `httpx`-based call against
  `generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent`
  works in the dev VPC against the real API;
* whether the descriptive-mode system prompt holds at the prompt
  boundary;
* what real-world latency a tiny H.264 clip produces.

This probe surfaces those answers in 2 hours instead of discovering
them when the eval team runs a real session.

## Approach

1. New module `backend/app/api/v1/admin/probe.py` exposing
   `POST /api/v1/admin/probe/vision-clip`. Admin-only via
   `require_role(UserRole.ADMIN)` (mirrors `emr.py:91`).
2. Multipart upload (`UploadFile = File(...)`) — same shape as
   `clips.py:upload_clip`. Optional form field
   `provider_override: VisionProviderKey | None` so an operator can
   probe OpenAI / Anthropic fallback paths through the SAME code
   path (Open/Closed).
3. Build a synthetic `MaskedClip` + `TranscriptSegment`. Upload the
   bytes to a temporary S3 key under `probe/<probe_id>.mp4`, call
   `registry.get_vision_provider_for_kind("clip", override=...).caption_clip(...)`
   with a timer, then **delete the temporary S3 object** in a
   `try/finally` regardless of provider outcome.
   * Probe S3 keys are isolated under `probe/` so they're trivially
     identifiable by lifecycle policy if a finally-block ever leaks
     (defense-in-depth — the deletion is the primary contract).
4. Catch every provider exception class, classify (`ProviderError`,
   `TimeoutError`, generic `Exception`), and return the diagnostic
   shape. Never re-raise — the probe REPORTS, never crashes.
5. Sanitise `error_message` before returning — `_scrub_secrets` walks
   the rendered string and replaces anything matching a Gemini /
   AWS / Anthropic / OpenAI key prefix or a full URL signature
   parameter with `***REDACTED***`.
6. Emit `VISION_CLIP_PROBED` audit event with
   `{provider, success, latency_ms, error_type}`. No PHI — the anchor
   is synthetic.
7. Bundled test fixture
   `backend/tests/fixtures/probe_clip.mp4` — 2s of solid blue 320x240,
   H.264 yuv420p, no audio. Generated once via `ffmpeg`; the recipe is
   documented in `backend/tests/fixtures/README.md` so operators can
   regenerate cleanly.
8. Operator doc `docs/dev/gemini-probe.md` covering the local +
   dev cloud `curl` invocations and the response interpretation.
9. New audit event type `VISION_CLIP_PROBED` in
   `backend/app/core/audit_events.py` with whitelist
   `{provider, success, latency_ms, error_type}`.

## Acceptance criteria

Each criterion is objectively verifiable by a named test or shell
command.

- [ ] AC-1: `POST /api/v1/admin/probe/vision-clip` returns 200 with
      `success=true` and a populated `caption.visual_description`
      when the registry-resolved provider's `caption_clip` returns a
      valid `FrameCaption`.
      Verified by `test_probe_happy_path_returns_caption`.
- [ ] AC-2: `latency_ms` is non-negative and > 0 (the timer must
      bracket the call) in the success response.
      Verified by `test_probe_latency_is_recorded`.
- [ ] AC-3: When the provider raises `ProviderError("auth failed")`,
      the response is 200 (probe never crashes) with `success=false`,
      `error_type="ProviderError"`, sanitized `error_message`, and
      `caption=null`.
      Verified by `test_probe_provider_error_returns_diagnostic`.
- [ ] AC-4: When the provider call times out (`asyncio.TimeoutError`),
      response carries `success=false`, `error_type="TimeoutError"`.
      Verified by `test_probe_timeout_returns_diagnostic`.
- [ ] AC-5: Calling as a `CLINICIAN` token returns 403.
      Verified by `test_probe_blocked_for_clinician_role`.
- [ ] AC-6: Missing `clip` field returns 422.
      Verified by `test_probe_missing_clip_returns_422`.
- [ ] AC-7: `Content-Type: image/jpeg` returns 400.
      Verified by `test_probe_rejects_non_mp4_content_type`.
- [ ] AC-8: Clip body > 5 MB cap returns 400 before any provider
      call.
      Verified by `test_probe_rejects_oversized_clip`.
- [ ] AC-9: AST scan of `app/api/v1/admin/probe.py` `logger.*` calls
      contains no API key, no clip bytes.
      Verified by `test_no_phi_in_probe_module_log_statements`.
- [ ] AC-10: Probe does NOT persist a session row (mock the DB session
      and assert no session-write call fires).
      Verified by `test_probe_does_not_create_session_row`.
- [ ] AC-11: Probe ALWAYS deletes the temp S3 object after the
      provider call (success OR failure). Verified by
      `test_probe_deletes_temp_s3_object_on_success` and
      `test_probe_deletes_temp_s3_object_on_failure`.
- [ ] AC-12: `VISION_CLIP_PROBED` audit event written on every call
      (success or failure) with `{provider, success, latency_ms,
      error_type}` kwargs.
      Verified by `test_probe_writes_audit_event_on_success` and
      `test_probe_writes_audit_event_on_failure`.
- [ ] AC-13: Bundled `backend/tests/fixtures/probe_clip.mp4` exists,
      is < 50 KB, decodes as MP4 with no audio track and ~2s
      duration. Verified by `test_bundled_probe_clip_is_valid_mp4`
      and a manual `ffprobe` check in the verification gate.
- [ ] AC-14: `provider_override="openai"` resolves the OpenAI vision
      provider via `get_vision_provider_for_kind` and the probe
      executes via that provider (single LSP code path).
      Verified by `test_probe_provider_override_resolves_alternate`.
- [ ] AC-15: `error_message` containing a fake API key shape
      (`AIza...`, `sk-...`, etc.) is scrubbed to `***REDACTED***`.
      Verified by `test_probe_scrubs_api_key_from_error_message`.
- [ ] AC-16: Full backend suite `pytest -q` passes (baseline 782).

## DRY / SOLID check

* **Existing helpers reused:**
  `require_role` (`auth/service.py`), `get_audit_log_service` /
  `write_audit` (`api/v1/_helpers.py`), `get_registry` +
  `get_vision_provider_for_kind` (`config/provider_registry.py`),
  `get_s3_client` + `FRAMES_BUCKET` (`core/s3.py`), `MaskedClip` /
  `TranscriptSegment` / `FrameCaption` / `ProviderError` /
  `ClipMaskingMetadata` (`core/types.py`), `VisionProviderKey`
  (`config/schema.py`), the multipart-shape pattern from
  `clips.py:upload_clip`, the multipart-test helper pattern from
  `tests/integration/test_clips_endpoint.py`.
* **New helper introduced?** Three:
  1. `_scrub_secrets(message: str) -> str` — sanitizes API keys
     from error messages. New (this is the FIRST + ONLY caller;
     introduced because letting an unscrubbed exception leak a key
     into a 200 response body is the worst possible regression).
     Lives module-local in `probe.py`; if a second site ever needs
     it, extract to `core/`.
  2. `_classify_error(exc: BaseException) -> str` — maps an
     exception to a stable `error_type` string for the response
     shape. New + module-local for the same reason.
  3. `VisionClipProbeResponse` Pydantic model — single use; lives
     next to its handler. Not reused elsewhere.
* **SRP:** the handler orchestrates (parse → S3 put → registry call
  with timer → audit → response). The registry resolves. The
  provider executes. The scrubber sanitizes. Four roles, four
  functions.
* **OCP:** `provider_override` is a `VisionProviderKey` Enum, not a
  `Literal["gemini", "openai", "anthropic"]`. New providers added
  to the enum will work through this probe with no code change in
  the handler. No `if provider == "gemini"` branching anywhere.
* **LSP:** every provider that implements `caption_clip` is probeable
  through the SAME handler. OpenAI / Anthropic clip captions
  (midpoint-still fallback) return the same `FrameCaption` shape, so
  the probe response carries them identically — only
  `degraded_to_frame=True` differs in the embedded caption.
* **DIP:** registry via `get_registry()`. Audit via the helpers
  module. S3 via `get_s3_client()`. **No direct SDK instantiation**
  in this PR's code.

## Out of scope

* No new feature flag — the probe is admin-only by virtue of
  `require_role(ADMIN)`; further gating is unnecessary for a
  diagnostic.
* No frame probe (the frame path is already exercised by every real
  session). Clip is the gap.
* No batch / multi-clip probe — single clip per call. An operator
  can re-invoke the endpoint.
* No provider-side cost reporting — we don't have a clean way to
  attribute the probe call's spend in the Google Cloud billing
  pull; the doc carries a `~$0.01 per call` rule-of-thumb instead.
* No persistence of probe results — diagnostic only. The audit row
  is the durable trail.

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/p1-fu-gemini-probe/backend && \
    python3 -m pytest tests/integration/test_vision_clip_probe.py -v` →
   all 15 AC tests pass.
2. `cd /Users/fsawadogo/aurion-lanes/p1-fu-gemini-probe/backend && \
    python3 -m pytest -q` → 797 passed (baseline 782 + 15 new tests).
3. `python3 -m ruff check .` → clean.
4. `ls -la backend/tests/fixtures/probe_clip.mp4 && \
    ffprobe -v error -show_streams backend/tests/fixtures/probe_clip.mp4 | \
    grep -E "codec_type|duration|codec_name"` →
   file exists; one `codec_type=video`, NO `codec_type=audio`,
   `codec_name=h264`, duration ~2.0s.
5. Local smoke (LocalStack — real provider call WILL fail with
   `error_type=ProviderError` because no GOOGLE_AI_API_KEY in dev
   shell; the route shape itself is verified):
   `curl -X POST http://localhost:8080/api/v1/admin/probe/vision-clip \
     -H "Authorization: Bearer ADMIN:$(uuidgen)" \
     -F clip=@backend/tests/fixtures/probe_clip.mp4 | jq '.'`
   → 200 with structured diagnostic body.

## Security implications

* **Admin-only.** The route is gated to ADMIN. CLINICIAN, EVAL_TEAM,
  and COMPLIANCE_OFFICER all see 403. The probe leaks no PHI even
  if reached — the anchor is synthetic — but the surface itself
  reveals provider state (which model, which latency profile) that
  should not be exposed beyond operators.
* **No PHI.** The probe uses a synthetic transcript anchor string
  (`"Range of motion examination"`). The operator-supplied clip
  bytes never reach a logger, never reach an audit row, and never
  reach the response body. They're streamed to a temp S3 key, read
  back by the provider, and deleted post-call.
* **No clip persistence after the call.** The probe writes the clip
  to S3 (KMS-encrypted, under `probe/<probe_id>.mp4`), calls the
  provider, then deletes the object in a finally-block. The S3
  bucket's existing TTL policy is the second line of defense if a
  finally-block leak ever happens.
* **API key scrub.** `_scrub_secrets` is called on every
  `error_message` before it leaves the handler. Gemini, OpenAI,
  Anthropic, and AWS access-key shapes are scrubbed to
  `***REDACTED***`.
* **No new audit-write path can mutate or delete an existing audit
  row.** `VISION_CLIP_PROBED` uses the same append-only
  `audit_service.write_event` path as every other event.
* **No descriptive-mode prompt change.** The probe re-uses the
  provider's existing `VISION_SYSTEM_PROMPT` — the constraint
  remains enforced at the prompt boundary.
* **Secrets via Secrets Manager.** No new env vars in this PR.
  `GOOGLE_AI_API_KEY` is read by the existing provider; we only
  surface its absence as a diagnostic.

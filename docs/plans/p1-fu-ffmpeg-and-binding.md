# P1-FU-FFMPEG — Install ffmpeg + fix probe param binding + dynamic model_id

## Task

`P1-FU-FFMPEG` — Three real bugs surfaced via live probe testing
against `https://api-dev.aurionclinical.com/api/v1/admin/probe/vision-clip`.
A single PR closes all three; they share the probe + clip-fallback
surface and a partial fix would leave the production fallback chain
half-broken.

### Bug 1 (critical) — ffmpeg missing in production ECS container

Probe with `provider_override=anthropic` AND `provider_override=openai`
both fail with:

```
"ffmpeg binary not found on PATH -- clip-to-still fallback requires
 the system `ffmpeg` binary to be installed."
```

The fallback chain (`registry.get_vision_provider_with_fallback`) is
designed so that if Gemini fails, Anthropic or OpenAI can pick up the
clip via `_clip_to_still.extract_midpoint_still`. Both shell out to
`ffmpeg`. The runtime image (`backend/Dockerfile`) installs `curl`
only. The chain is broken in production until ffmpeg is in the image.

### Bug 2 — `provider_override` declared as `Form()`, silently ignores query string

`backend/app/api/v1/admin/probe.py:234`:

```python
provider_override: Optional[VisionProviderKey] = Form(default=None),
```

FastAPI's `Form()` only reads from multipart body fields. Operators
using `?provider_override=anthropic` as a query string get silently
ignored — the parameter defaults to `None`, AppConfig's default
(Gemini) flows through. No error. The Postman collection and the
operator doc both assume query-string usage.

### Bug 3 (cosmetic) — stale model_id constant

`backend/app/api/v1/admin/probe.py:200-204`:

```python
VisionProviderKey.ANTHROPIC: "claude-sonnet-4-5",
```

But `backend/app/modules/providers/vision/anthropic.py:40` is already
`_MODEL = "claude-sonnet-4-6"`. The probe lies about which model is
running. Operators triage off this field.

## Why

* **Pilot blocking.** `CLAUDE.md` §Error handling: "Provider unavailable
  → fallback to next, log it." A missing OS-level dep silently breaks
  this contract for the entire `vision_clip` provider rotation. The
  pilot at CREOQ/CLLC needs every fallback path to work.
* **Diagnostic endpoint must tell the truth.** A probe that lies about
  which model it called (bug 3) or silently substitutes a different
  provider (bug 2) is worse than no probe.
* **Single PR.** Bugs 1 + 2 + 3 are all probe / clip-fallback surface.
  Splitting them invites partial deploys and a half-broken fallback
  chain mid-pilot.

## Approach

### Bug 1 — install ffmpeg in `backend/Dockerfile`

Add `ffmpeg` to the existing apt-get install line. Add a
`RUN ffmpeg -version` build step right after so a future base-image
swap that drops the package fails the build, not a 500 in production.

Image-size cost: ~70 MB. Acceptable for an API container that
already carries Python + transitive deps.

### Bug 2 — swap `Form()` → `Query()` on `provider_override`

`Query(default=None)` is the cleanest fix. The brief flags two
options:

1. Accept BOTH query and form (two parameters, fall back to each other).
2. Query only — natural shape for diagnostic endpoints + curl + Postman.

Going with option 2: query only. The brief also notes "matches the
Postman collection's existing assumption." Operator doc already uses
multipart for `clip` (the file) but query strings everywhere the user
expects a query string. Mixing form fields for some parameters and
query strings for others is the worst case — pick one boundary per
parameter.

The existing test suite passes `provider_override` via `data=` (form).
Update to `params=` (query) — three tests in
`tests/unit/test_probe_provider_override.py` + four in
`tests/integration/test_vision_clip_probe.py`.

### Bug 3 — import provider `_MODEL` constants instead of duplicating

Each provider already exposes `_MODEL` as a module-level constant:

* `backend/app/modules/providers/vision/gemini.py:42` — `_MODEL = "gemini-2.5-pro"`
* `backend/app/modules/providers/vision/openai.py:38` — `_MODEL = "gpt-4o"`
* `backend/app/modules/providers/vision/anthropic.py:40` — `_MODEL = "claude-sonnet-4-6"`

Import them into `probe.py` and rebuild `_PROVIDER_MODEL_ID` from
those constants. Single source of truth — a future model bump in a
provider module automatically propagates to the probe.

Same change in the test suite: `tests/unit/test_probe_provider_override.py`
and `tests/integration/test_vision_clip_probe.py` had hardcoded
`"gpt-4o"` and `"claude-sonnet-4-5"` assertions; both now import the
provider's `_MODEL` constant so the assertions stay in lockstep.

### New integration test — pre-verify ffmpeg-enabled fallback round trip

`backend/tests/integration/test_clip_fallback_chain_with_ffmpeg.py`
pre-verifies the Python-side contract that the Dockerfile fix enables
in production:

1. Mock `extract_midpoint_still` (stands in for the now-present
   `ffmpeg` binary) to return a synthetic still.
2. Mock `provider.caption_frame` to return a valid `FrameCaption`.
3. POST to the probe with `?provider_override=anthropic`.
4. Assert `success=true`, `provider_used=anthropic`, `model_id` from
   the source-of-truth constant, `caption.degraded_to_frame=true`.

Parallel coverage for OpenAI. Plus a regression-guard test for the
ffmpeg-missing path: the probe must surface it as a structured 200
diagnostic, never crash.

## Acceptance criteria

* [ ] AC-1: `backend/Dockerfile` includes `ffmpeg` in the apt-get
      install line AND a `RUN ffmpeg -version` verification step.
      Verified by inspection (CI builds the image; the verification
      step fails the build if the binary is missing).
* [ ] AC-2: `probe_vision_clip` declares `provider_override` as
      `Query(default=None)` — query string is the public contract.
      Verified by reading the handler signature.
* [ ] AC-3: All updated tests in
      `tests/unit/test_probe_provider_override.py` (5 tests) pass
      with `provider_override` passed as `params=`.
* [ ] AC-4: All updated tests in
      `tests/integration/test_vision_clip_probe.py` (20 tests) pass.
* [ ] AC-5: `_PROVIDER_MODEL_ID` in `probe.py` is built from
      `app.modules.providers.vision.{gemini,openai,anthropic}._MODEL`
      constants. Verified by source inspection AND by the new test
      that imports `_ANTHROPIC_MODEL` and asserts the probe response
      matches.
* [ ] AC-6: New test file
      `tests/integration/test_clip_fallback_chain_with_ffmpeg.py`
      passes (3 tests). Covers Anthropic happy path, OpenAI happy
      path, and ffmpeg-missing regression guard.
* [ ] AC-7: `docs/dev/gemini-probe.md` shows the query-string
      invocation for `provider_override` AND a "Verifying the
      fallback chain" section documenting the post-ffmpeg-fix
      `degraded_to_frame=true` expectation.
* [ ] AC-8: Full backend suite stays green — baseline 851, expected
      854+ after this PR (3 new tests).
* [ ] AC-9: `ruff check backend/` clean.

## DRY / SOLID check

* **Existing helpers to reuse**: provider `_MODEL` constants in each
  vision provider module, `extract_midpoint_still` in
  `_clip_to_still.py`, `_multipart` test helper, `mock_audit` /
  `mock_s3` fixtures, ASGI `app_client` fixture pattern.
* **New helpers introduced**: none. The new test file copies the
  fixture shape from `test_vision_clip_probe.py` (which is itself
  the second site for that pattern); a third occurrence would
  warrant extracting to `tests/conftest.py`. We hold the line at
  two near-copies for now.
* **DRY (bug 3)**: model id strings live in ONE place per provider
  (`vision/<provider>.py:_MODEL`). The probe imports; tests import;
  no string duplication.
* **SRP**: Dockerfile concern is OS-level deps; probe concern is
  HTTP boundary + diagnostic shape; provider concern is model id
  + transport. Each layer owns one responsibility.
* **OCP**: adding a new vision provider doesn't require touching
  `_PROVIDER_MODEL_ID` mapping shape — it just needs an entry that
  imports the provider's `_MODEL` constant.

## Security implications

* **PHI**: untouched. The probe still uses the synthetic session id
  `00000000-…`, still writes audit rows with no PHI, still scrubs
  API keys from error messages.
* **Audit log**: schema and write semantics unchanged. The probe
  audit event still emits on success + failure.
* **AppConfig**: untouched. The override is a per-request override;
  AppConfig defaults still flow through when no override is sent.
* **Container surface**: ffmpeg is a well-known package shipped from
  Debian's main repo, used by millions of Python video pipelines.
  No additional attack surface beyond what every container with
  `ffmpeg` carries.

## Out of scope

* Changing the fallback chain order. AppConfig still routes
  `vision_clip` to Gemini by default; this PR just makes the
  fallback path runnable.
* Refactoring `_PROVIDER_MODEL_ID` from a `dict` to a property /
  function. The brief suggests this as an option; a dict built
  from imports is sufficient and simpler.
* Bumping the AppConfig `vision_clip` default. Out of band.

## Test plan (executable)

1. `cd backend && python3 -m pytest tests/unit/test_probe_provider_override.py tests/integration/test_vision_clip_probe.py tests/integration/test_clip_fallback_chain_with_ffmpeg.py -v` → all pass.
2. `cd backend && python3 -m pytest -q` → baseline 851 → 854+.
3. `cd backend && ruff check .` → clean.
4. `docker build -t aurion-api:p1-fu-ffmpeg backend/` — if Docker is
   available locally; the `RUN ffmpeg -version` step fails fast if
   the apt-get install dropped the package.
5. Post-merge cluster verification (operator runs):
   ```bash
   curl -X POST "https://api-dev.aurionclinical.com/api/v1/admin/probe/vision-clip?provider_override=anthropic" \
     -H "Authorization: Bearer $ADMIN_JWT" \
     -F clip=@backend/tests/fixtures/probe_clip.mp4 \
     | jq '{provider_used, model_id, success, degraded: .caption.degraded_to_frame}'
   ```
   Expect `{provider_used: "anthropic", model_id: "claude-sonnet-4-6", success: true, degraded: true}`.

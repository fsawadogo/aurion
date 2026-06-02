# P1-2 — Native Clip Captioning + Still-Fallback (Gemini + OpenAI + Anthropic)

Plan reference: `/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`
(the full dual-mode visual evidence plan — frames + clips with runtime selection,
"Per-provider implementations" matrix).

P1-1 (PR-merged) added the `caption_clip` abstract method to the `VisionProvider`
ABC and shipped `NotImplementedError("clip captioning lands in P1-2")` stubs in
each concrete provider. P1-2 replaces those stubs with real implementations.

## Why

Gemini 2.5 Pro is the only frontier model with native video-clip understanding
today. For motion-heavy moments (ROM exams, gait analysis, surgical technique,
dressing-change technique), a 7-second clip gives a description like *"patient
demonstrated abduction to approximately 140° then visibly winced and stopped"* —
something three 1-fps stills only approximate by luck.

OpenAI and Anthropic don't ingest video natively, but the Stage-2 dispatcher
must stay evidence-kind-agnostic (LSP). The pragmatic answer is a lossy
fallback: extract the midpoint still via ffmpeg, run the existing
`caption_frame` path, and tag the resulting citation `degraded_to_frame=True`
so the reviewer surfaces a "still extracted from clip" badge.

## Scope of this PR (P1-2)

Backend, additive only, all three providers light up `caption_clip`.

- `modules/providers/vision/gemini.py` — **native** path. Fetches the clip
  bytes from S3, sends them as `inline_data` (mime `video/mp4`) in a
  `generateContent` call alongside the existing descriptive-mode system
  prompt. Appends a clip-specific user message: *"This is a video clip
  with duration {duration_ms}ms. Describe what is observable across the
  clip, including motion."*. AppConfig vision params (temperature /
  max_tokens / responseSchema) — same as `caption_frame`.
- `modules/providers/vision/openai.py` — **lossy still-fallback**. Calls
  the shared `extract_midpoint_still` helper to get a synthetic
  `MaskedFrame` from the clip MP4, then delegates to `self.caption_frame`
  for the actual GPT-4o request (DRY: no duplicate request logic). Flips
  `evidence_kind="clip"`, `duration_ms=clip.duration_ms`, and
  `degraded_to_frame=True` on the returned caption via `model_copy`.
- `modules/providers/vision/anthropic.py` — same still-fallback shape as
  OpenAI. Uses the same shared helper (DRY).
- **New** `modules/providers/vision/_clip_to_still.py` — single source
  of truth for the ffmpeg midpoint extraction. Reads MP4 bytes from S3
  via the existing `get_s3_client()` helper (DIP), invokes `ffmpeg` to
  pull the midpoint frame, and returns a synthetic `MaskedFrame` whose
  `s3_key` points back at the original clip so audit / debugging can
  trace the still to its source. Used by both OpenAI and Anthropic; NOT
  used by Gemini.
- `core/types.py` — `FrameCaption.degraded_to_frame: bool = False`
  (additive, default preserves byte-identical behavior on the frame path).
- `requirements.txt` — `ffmpeg-python` (Python wrapper around the system
  `ffmpeg` binary; the binary itself ships in the runtime image).
- `tests/unit/test_clip_captioning.py` — full coverage per AC matrix.
- `tests/unit/test_clip_evidence_schema.py` — extend the P1-1 lock test
  to cover the new `degraded_to_frame` default.

## Acceptance criteria

- [ ] AC-1: Gemini happy path — mocked Files API + `generateContent`
      returns valid JSON → `FrameCaption` emits with
      `evidence_kind="clip"`, `duration_ms=clip.duration_ms`,
      `provider_used="gemini"`, `degraded_to_frame=False`.
- [ ] AC-2: OpenAI fallback path — mocked S3 fetch + mocked ffmpeg
      midpoint extract + mocked GPT-4o call → returns `FrameCaption`
      with `evidence_kind="clip"`, `duration_ms=clip.duration_ms`,
      `provider_used="openai"`, `degraded_to_frame=True`.
- [ ] AC-3: Anthropic fallback path — same shape as OpenAI AC-2 with
      `provider_used="anthropic"`.
- [ ] AC-4 (DRY): both OpenAI and Anthropic call the SAME
      `extract_midpoint_still` helper; assertion via mock call count or
      import verification — there is exactly one ffmpeg invocation site
      in the codebase.
- [ ] AC-5 (fallback chain): each provider raises `ProviderError` on 5xx
      so the registry's `get_vision_provider_with_fallback` can trip to
      the next provider.
- [ ] AC-6 (ffmpeg missing): `extract_midpoint_still` raises a clear
      error mentioning the `ffmpeg` binary when the system invocation
      fails with `FileNotFoundError`.
- [ ] AC-7 (no PHI): regex test scans `caption_clip` log statements
      across all three providers — no full S3 keys, patient identifiers,
      or transcript content. Truncated key prefixes (≤12 chars) are
      acceptable.
- [ ] AC-8 (LSP): `FrameCaption` returned from each provider's
      `caption_clip` matches the schema returned from `caption_frame`,
      with `evidence_kind="clip"` + `duration_ms` set as the only
      structural difference; downstream conflict-detection logic stays
      evidence-kind-agnostic.

## Out of scope

- `POST /api/v1/clips/{session_id}` endpoint — lands in P1-3.
- Stage 2 dispatch (frame-vs-clip routing in `vision/service.py`) — P1-3.
- iOS ring buffer / clip extraction / masking — P1-4..P1-6 (P1-4 merged).
- Eval harness for `clips_only` vs `frames_only` — Phase 2 work.

## DRY / SOLID check

- **Existing helpers reused**: `VISION_SYSTEM_PROMPT`,
  `VISION_RESPONSE_SCHEMA`, `build_frame_caption`,
  `get_config().model_params.vision.*`, `get_s3_client()`,
  `load_frame_image_base64` (Gemini bypasses this for video bytes;
  the still-fallback path uses it indirectly via `caption_frame`).
- **New helper introduced**: `_clip_to_still.extract_midpoint_still`.
  Justification — this would be the THIRD copy of ffmpeg+S3 plumbing
  (OpenAI fallback, Anthropic fallback) if inlined. Single source of
  truth satisfies the §6c "rule of three" check.
- **OCP**: behavior extension lives in the provider classes via the
  existing `caption_clip` abstract method — no `if provider_key == ...`
  branches added. The dispatcher in P1-3 will route by `evidence_kind`,
  not by provider key.
- **LSP**: every provider's `caption_clip` returns the same
  `FrameCaption` schema (see AC-8). `degraded_to_frame` is a uniform
  field; both native and fallback paths set it explicitly.
- **DIP**: providers reach S3 via `get_s3_client()` only; the helper
  takes the bucket name as a parameter so testing can inject a mock
  without touching boto3 directly.

## Security implications

- Descriptive-mode system prompt re-used verbatim from `caption_frame`
  (CLAUDE.md §"Single Most Important Constraint"). The clip-specific
  user message is descriptive ("describe what is observable") only —
  no interpretive or diagnostic language.
- No PHI in logs: the OpenAI / Anthropic fallback log lines truncate the
  S3 key to a 12-character prefix; no patient identifiers or transcript
  text crosses the log boundary. AC-7 enforces this with a regex test.
- Vision calls still route through the registry (P1-3 will dispatch
  per `evidence_kind`); this PR only extends provider impls.
- Provider keys remain in env-var / Secrets Manager; no new secret
  surfaces introduced.
- Audit log is untouched in this PR; clip-upload audit events land
  with the new endpoint in P1-3.

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m pytest tests/unit/test_clip_captioning.py -v`
   — all new ACs pass.
2. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m pytest tests/unit/ -q`
   — full unit suite passes (no regressions vs 713 baseline; expect
   ≥720 with the new tests).
3. `cd /Users/fsawadogo/aurion-lanes/backend/backend && python3 -m ruff check .` — clean.
4. PHI scan: `python3 -m pytest tests/unit/test_clip_captioning.py::test_no_phi_in_caption_clip_logs -v` — passes.

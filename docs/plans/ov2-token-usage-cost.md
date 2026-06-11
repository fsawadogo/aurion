## Task
OV-2 — Per-call token usage + cost capture for note_gen and transcription (#73)

## Why
#73's usage panel shows "—" for tokens/cost on every stage: nothing writes
provider_usage.cost_usd or tokens today (the rate sheet exists but its only
consumer is clip pilot-metrics). The audit listed this as the #73 remainder:
"note_gen/transcription cost rates once the provider base surfaces per-call
usage."

## Approach
- Move `vision/cost_rates.py` → `core/cost_rates.py` (CLAUDE.md: shared
  infra lives in core; also kills a comment-level core→vision inversion).
  Add `estimate_audio_cost_usd_micros(provider, seconds)` for duration-
  priced transcription (whisper self-hosted = 0; assemblyai per-hour rate,
  source-commented + approximate like the token table).
- New `providers/usage_context.py`: a ContextVar-based per-call usage
  collector (`set_call_usage` / `consume_call_usage`) — async-task-local so
  concurrent calls can't cross-contaminate, and NO provider signature
  changes (LSP intact: generate_note still returns Note).
- The 3 note_gen providers set usage after parsing their response
  (anthropic `usage.*`, openai `usage.prompt/completion_tokens`, gemini
  `usageMetadata.*TokenCount`) with their `_MODEL`.
- `note_gen/service._record_provider_usage` consumes the context →
  passes input/output tokens + model_name + cost (token rates) into
  `record()` (params already exist, never fed).
- `transcription/service` success path: duration from the last segment's
  end_ms → audio cost; provider name keys the rate.

## Acceptance criteria
- [ ] AC-1: usage_context round-trip + task isolation + consume-resets —
      pytest tests/unit/test_usage_context.py
- [ ] AC-2: each note_gen provider sets usage from its (mocked) response
      shape — pytest tests/unit/test_note_gen_usage_capture.py
- [ ] AC-3: note_gen record() receives tokens+model+cost>0 for a known
      model — same module
- [ ] AC-4: audio cost estimator: whisper→0, assemblyai>0, unknown→0 —
      pytest tests/unit (cost rates module)
- [ ] AC-5: full backend suite green; clip-metrics tests still pass after
      the module move

## DRY / SOLID check
- Reuse: estimate_cost_usd_micros + USD_MICROS scaling (moved, not
  duplicated); try_record_provider_usage's existing token/cost params.
- New helper: usage_context — new capability, not a third copy; ContextVar
  chosen over mutable provider state (registry providers are shared
  singletons → races) and over signature changes (3 providers + stubs).
- iOS: n/a.

## Out of scope
- Vision per-call cost into provider_usage (clip spend already lands in
  pilot_metrics; unify later).
- Live AppConfig-driven rate sheet (static, source-commented constants).

## Test plan (executable)
1. cd backend && python3 -m pytest tests/unit/test_usage_context.py tests/unit/test_note_gen_usage_capture.py -q
2. cd backend && python3 -m pytest tests/unit -q
3. grep -rn "vision.cost_rates" backend/app → no hits (move complete)

## Security implications
None: token counts, model ids, and dollar estimates are non-PHI numerics;
no new logging of content; provider calls still registry-routed.

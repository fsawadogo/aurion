# P1-FU-METRICS — pilot_metrics clip-aware columns + Stage 2 emitter

**Canonical plan reference:** Phase 1 dual-mode visual evidence — gap audit
on the eval-team observability surface for Phase 2's 20-session evaluation.

**Type:** backend-only follow-up. Adds 5 nullable columns to the existing
`pilot_metrics` Postgres table, extends the SQLAlchemy model + admin read
endpoint to surface them, and wires a per-session aggregator into the
Stage 2 vision dispatch loop. Introduces a small cost-rate module so the
"USD spend per session" number isn't conjured at the call site.

## Task

P1-FU-METRICS — give the eval team per-session clip cost, latency, byte,
fallback-to-still, and count numbers so Phase 2 can compare providers
quantitatively + plan production scale.

## Why

Phase 1 shipped clip processing end-to-end. The existing `pilot_metrics`
row carries Stage 1/Stage 2 wall-clock latency, completeness, conflict
rate — all frame-only KPIs from the pre-clip world. With clips landing
in Stage 2 today, the eval team has no path to ask "how much did Gemini
2.5 Pro cost on session X" or "did we degrade to still on Y% of clips
this session" without scraping logs.

CLAUDE.md §"Passive Data Collection" says "Stored in `pilot_metrics`
PostgreSQL table. No PHI. 100% of sessions." This PR extends the same
table — same access controls, same shape — with 5 nullable additive
columns. Old rows decode as `0`/`null`; no backfill.

## Approach

**1. Migration — `2026_06_03_0024_pilot_metrics_clips.py`**

5 nullable columns, integer-typed so arithmetic is precise (cost stored
as USD micros, not float):

| Column | Type | Default | Meaning |
|---|---|---|---|
| `clip_count` | `INTEGER NULL` | `0` | Count of evidence items with `kind == "clip"` processed in Stage 2 |
| `clip_bytes_uploaded` | `INTEGER NULL` | `0` | Total uploaded MP4 bytes (post-masking), summed from S3 metadata |
| `clip_avg_latency_ms` | `INTEGER NULL` | — | Mean per-clip `caption_clip` wall-clock |
| `clip_vision_spend_estimate_usd_micros` | `INTEGER NULL` | — | Σ(input_tokens × in-rate + output_tokens × out-rate); USD × 1e6 |
| `clip_degraded_to_frame_count` | `INTEGER NULL` | `0` | Count of returned `FrameCaption`s with `degraded_to_frame=True` |

Downgrade drops all 5. Reversible.

**2. SQLAlchemy — `app/core/models.py:PilotMetricsModel`**

Five `Mapped[int | None]` columns mirroring the migration; the
existing `Mapped[float | None]` style on `template_section_completeness`
is the template.

**3. Cost rates — `app/modules/vision/cost_rates.py`**

New module. Static dict keyed by `provider → model → {input, output}`
in USD-per-million-tokens (float, decimal-precise math only at the
edge — the table is authoritative). `estimate_cost_usd_micros(...)`
returns an integer USD-micros value; unknown provider/model returns
`0` and logs INFO ("rate sheet missing for X/Y, returning 0"). Phase 2
will tune the table; the contract stays the same.

DRY: this is the single rate-lookup site. Note-gen / transcription
spend estimation can import from here in a follow-up.

**4. Stage 2 emitter — `app/modules/vision/service.py`**

Two changes to `caption_visual_evidence`:

a. Track per-clip telemetry in a list local to the dispatch loop:
   `(provider_used, model, latency_ms, input_tokens, output_tokens,
   degraded_to_frame, s3_key)`. Frames are skipped — we measure clip
   spend specifically.

b. At completion (after `asyncio.gather` returns), if at least one
   clip was processed, call a new helper `_record_clip_metrics(...)`
   that upserts the `pilot_metrics` row for the session. Identical
   shape to the existing `_record_stage1_latency` upsert in
   `api/v1/transcription.py`; we DRY this by promoting the upsert
   helper to a shared utility in `app/modules/session/` (or by
   following the same try/except + INSERT-or-UPDATE pattern in place,
   since `transcription.py` lives at the API layer and `service.py`
   lives at the module layer — extracting to a shared module-scope
   helper is the cleaner long-term move).

Audit: token counts aren't populated by the current vision providers
(`Note` on provider_usage.input_tokens lives in the model but isn't
filled by the vision dispatch). For now the emitter accepts whatever
the provider returns via a small `caption.usage` extension; missing
tokens → `0` spend, never crash. The `FrameCaption` schema stays
unchanged this PR — the emitter relies on the dispatch timer for
latency and falls back to `0` for tokens. A follow-up will surface
tokens through `caption_frame`/`caption_clip` once providers expose
them; the rate sheet is already wired.

**Pragmatic scope of this PR**: we land the columns, the cost rate
module, and the aggregator. The token-source plumbing (vision
providers returning `usage`) is a separate follow-up; for now,
input_tokens/output_tokens default to `0` and the spend estimate is
`0` until providers populate them. Latency, bytes, count, and
degraded-to-frame count work today.

**5. Admin read endpoint — `app/api/v1/admin/metrics.py`**

Extend `PilotMetricResponse` with the 5 new optional fields and surface
them in `/api/v1/admin/metrics`. EVAL_TEAM + ADMIN; CLINICIAN cannot
read (unchanged role gate). Old clients ignore the new fields
(additive JSON).

## Acceptance criteria

- [ ] AC-1: Alembic upgrade adds 5 columns to `pilot_metrics`; verified
      by `python3 -m alembic upgrade head && python3 -m alembic
      downgrade -1 && python3 -m alembic upgrade head` running clean.
- [ ] AC-2: `PilotMetricsModel` exposes the 5 columns with correct
      types; verified by `tests/unit/test_pilot_metrics_clip_aggregation.py`
      asserting model attribute presence + type.
- [ ] AC-3: Stage 2 emitter aggregates clip count + bytes + mean
      latency + degraded count from a mixed-evidence run; verified by
      `test_pilot_metrics_clip_aggregation.py::test_aggregate_mixed_evidence`.
- [ ] AC-4: `clip_avg_latency_ms` is the arithmetic mean of a 3-clip
      list; verified by `test_pilot_metrics_clip_aggregation.py::test_avg_latency`.
- [ ] AC-5: Cost rate fallback for unknown provider returns 0 and
      emits an INFO log; verified by
      `test_pilot_metrics_clip_aggregation.py::test_cost_rate_unknown_provider`.
- [ ] AC-6: Admin endpoint serializes the new fields and rejects
      CLINICIAN role; verified by existing admin/metrics suite +
      one new field-presence assertion.
- [ ] AC-7: No PHI in the new emitter logging path; verified by
      `@compliance-checker` grep.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - `_record_stage1_latency` in `api/v1/transcription.py` — same
    upsert pattern; the emitter follows the same structure
    (try/except, `select ... session_id`, branch on `None`,
    `db.flush()`).
  - `try_record_provider_usage` in `providers/usage_service.py` —
    already records per-call telemetry; the clip emitter is the
    per-session rollup of that surface.
  - `get_audit_log_service`, `get_registry` — unchanged.
- **New helper introduced?**: yes — `estimate_cost_usd_micros`. This
  is the FIRST cost-estimate function in the codebase, but Phase 2
  needs it; subsequent spend metrics (note-gen, transcription) will
  import from the same module. We're standing up the abstraction at
  the right boundary (lookup table + one calculator), not branching
  inline.
- **DRY rollup helper**: the per-session pilot_metrics upsert pattern
  has two call sites after this PR (stage1 latency in
  `transcription.py`, clip metrics here). At three, we extract into
  `modules/session/pilot_metrics_repo.py`. Today we duplicate the
  pattern in place per §6c's rule of three.

## Out of scope

- Token plumbing through `caption_frame`/`caption_clip` (deferred
  follow-up; without it, `clip_vision_spend_estimate_usd_micros`
  defaults to `0`).
- Web-portal chart for clip metrics (separate Phase 2 surface).
- Per-clip cost breakdown row (only the session rollup lands here).
- Note-gen / transcription cost estimation (same rate sheet will be
  reused; not this PR).

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/p1-fu-metrics/backend && python3 -m pytest tests/unit/test_pilot_metrics_clip_aggregation.py -v` → all pass
2. `cd .../backend && python3 -m pytest -q` → 802+ pass, no regressions
3. `cd .../backend && python3 -m ruff check .` → clean
4. `cd .../backend && python3 -m alembic upgrade head && python3 -m alembic downgrade -1 && python3 -m alembic upgrade head` → reversible

## Security implications

- No new PHI surface. The emitter receives `(session_id, count,
  bytes, latency, spend, degraded_count)` — all aggregate integers,
  zero patient identifiers.
- No new audit-log write paths.
- Admin endpoint stays behind EVAL_TEAM/ADMIN role gate; CLINICIAN
  cannot read (unchanged).
- Cost rate values are public information (provider pricing pages)
  — no secrets, no API keys.
- Emitter wraps the upsert in `try/except` per `_record_stage1_latency`
  precedent so a metrics-table write failure can never break Stage 2.

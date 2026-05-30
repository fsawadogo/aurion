# Plan for #73 — Provider cost & usage dashboard (foundation)

## Task
**#73** — Per‑provider operational instrumentation surface so admins can
see the $/latency/fallback‑rate trade‑off behind the runtime provider
switch shipped earlier. Foundation slice ships **latency + call counts
+ fallback rate** persisted per call, plus an aggregation endpoint.
Tokens & $ cost arrive in a follow‑up that refactors the
`base.py` provider interface to surface `usage` from each call.

## Why
The provider registry is now runtime‑switchable (per‑call override +
DB override + AppConfig). The CTO and EVAL team need data to choose
which provider to pin: "anthropic is 200ms slower but its fallback rate
is half openai's" — that conversation needs a dashboard. CLAUDE.md
§"Pilot Metrics" already tracks `stage1_latency_ms`/`stage2_latency_ms`
per session; this PR introduces a sibling: per‑provider‑call telemetry
the registry boundary writes on every call.

## Approach
- **Model + migration** (`ProviderUsageModel`, migration 0009): id PK,
  `provider_type` ("transcription" | "note_generation" | "vision"),
  `provider_name` (e.g. "openai"), `model_name` (nullable, e.g. "gpt-4o"),
  `operation` ("generate_note" | "caption_frame" | "transcribe"),
  `session_id` (nullable FK), `input_tokens` (nullable), `output_tokens`
  (nullable), `cost_usd` (nullable numeric), `latency_ms`, `success`,
  `fallback_used`, `created_at`. Tokens/cost nullable so this PR can ship
  latency + counts without waiting on the interface refactor.
- **Service** (`app/modules/providers/usage_service.py`):
  `record(...)` (one row per call) + `aggregate(...)` (totals + per‑
  provider rollup over a date window).
- **Wiring** (one explicit site for the foundation):
  `app/modules/note_gen/service.py` wraps `provider.generate_note(...)`
  with `time.monotonic()`, records success / failure / fallback. Other
  sites (vision, transcription) follow in a follow‑up PR — same
  pattern, 5 lines per site.
- **Endpoint**: `GET /api/v1/admin/providers/usage` — date‑range
  filterable, returns `{ totals, by_provider }`. ADMIN+COMPLIANCE gated.
- **Test plan**: 6+ unit tests via the AsyncMock pattern; smoke against
  the local stack.

## Acceptance criteria
- [ ] **AC-1**: migration 0009 creates `provider_usage` table.
- [ ] **AC-2**: `record(...)` persists a row; verified by
      `pytest tests/unit/test_provider_usage.py::TestRecord`.
- [ ] **AC-3**: `aggregate(...)` rolls up calls / latency / fallback by
      provider; verified by `pytest …::TestAggregate`.
- [ ] **AC-4**: Stage 1 note generation now records a usage row on
      success **and** on raised exception (success=False), verified by
      the note_gen unit suite still passing + a `test_records_on_success`
      bridging the registry call site.
- [ ] **AC-5**: `GET /api/v1/admin/providers/usage` returns 200 with
      `{totals, by_provider}` shape; clinician role → 403.
- [ ] **AC-6**: Backend suite stays green (301 → ~310 passing).

## DRY / SOLID check
- **Existing helpers reused**: `Depends(get_db)`, `require_role`,
  `utcnow`, the admin‑router aggregator pattern, the AsyncMock test
  helper used by `test_alert_service.py` / `test_template_overrides.py`.
- **New helper introduced?** Yes, `ProviderUsageService` —
  new vertical (provider telemetry); not a third copy of an existing
  pattern. Mirrors the same model + service + router shape as
  `alerts` and `template_overrides`.
- **OCP**: the wiring is in `note_gen/service.py` as a wrapper around
  the existing registry call; adding more call sites (vision,
  transcription) doesn't touch the service, only the new call site.
- **DIP**: db injected via `Depends(get_db)`.

## Out of scope (follow-ups)
- `base.py` provider‑interface change to return a `ProviderUsage` dataclass
  carrying `input_tokens` / `output_tokens` / `cost_usd` per call. Once
  that lands, `record(...)` is called with the real values instead of
  nulls.
- Vision + transcription call‑site instrumentation (5‑line each;
  identical pattern).
- Web Portal "Providers" dashboard page (totals card, latency chart,
  fallback‑rate row).
- Cost‑model catalog (price per provider × model × token type) — needs
  product decision on whether to track at the row level or compute at
  aggregation time from a catalog.
- Time‑bucketing in the aggregation endpoint (hourly/daily). The
  current endpoint returns totals over the window only; the time‑series
  ships when the dashboard page does.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_provider_usage.py -v`
   → all pass
2. `docker-compose exec aurion-api alembic upgrade head` → 0008 → 0009
3. `curl -H "Authorization: Bearer <admin>" localhost:8080/api/v1/admin/providers/usage`
   → 200 + `{totals: {...}, by_provider: [...]}`
4. `cd backend && python3 -m pytest -q` → 301 → ~310, no regressions

## Security implications
- **No PHI**: usage rows carry provider name + latency + success +
  optional session_id. No transcript / patient content.
- **session_id is nullable** so calls outside a session context (e.g.
  future provider‑health pings) record cleanly.
- **Best‑effort record**: the trigger site wraps `record(...)` in a
  try/except so a telemetry‑DB hiccup never alters the audited / 5xx
  path — same pattern as the alerts wiring in #76.
- **Role gated** (ADMIN + COMPLIANCE_OFFICER); cost data could be
  business‑sensitive.

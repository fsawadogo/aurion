# Plan — WEB-METRICS-CHARTS pilot metrics time-series charts

## Task

`WEB-METRICS-CHARTS` — replace the dashboard's current "averages-only +
fake-bucketed weekly bar" view with per-day time-series for each of
the 8 pilot metrics (CLAUDE.md §"Passive Data Collection — Pilot
Metrics"). Backend adds a daily-aggregation endpoint; frontend reworks
the dashboard to consume it.

## Why

The spec (`web-portal-spec.md` §Feature 5) calls for *"Time-series
charts per metric across pilot duration."* The dashboard today shows:

  - 4 summary cards (totals, not trends)
  - 8 metric cards (averages, no time axis)
  - 2 "charts": `Last 7 days` (now properly bucketed by created_at after
    the W009 data-fidelity fix) and `By Specialty` (count distribution)

Eval reviews during the pilot will want to see whether (say)
`stage1_latency_ms` is trending up over time — averages hide that.
The endpoint also unblocks future per-clinician trend views without
a frontend re-design.

## Approach

### Backend

New endpoint `GET /api/v1/admin/metrics/timeseries` (extends the
existing admin/metrics module):

  - Query params: `from` (ISO date), `to` (ISO date), `specialty`
    (optional), `clinician_id` (optional). Default window: last 14 days.
  - Aggregation: `DATE_TRUNC('day', created_at)` per row in
    `pilot_metrics`, filtered, then AVG over each numeric metric and
    SUM over `session_completeness` (boolean → 1/0).
  - Response: `MetricTimeseriesResponse` with
    - `from`, `to`, `bucket`: "day" (forward-compat for later week/hour)
    - `buckets`: list of `MetricTimeseriesBucket` rows
  - `MetricTimeseriesBucket`: `date` (ISO date), `session_count`,
    + each of the 8 metrics as `Optional[float]` (null = no data that
    day). For boolean `session_completeness`: % of sessions that day
    that had all 8 metrics logged.

Role gate: `require_role(EVAL_TEAM, ADMIN)` — same as `GET /metrics`.

### Frontend

Dashboard rewrite. Drop the fake `Last 7 days` and `By Specialty` cards;
replace with:

  - **Date range picker** — `from` / `to`, defaults to last 14 days.
  - **8 small-multiples panels** — one per metric. Each panel has:
    - The metric's average across the window (top-right)
    - A CSS-only sparkline-style bar chart of the daily series
      (no chart library — keep dependency surface stable; ECharts /
      recharts is a separate decision and can land in a follow-up
      PR)
    - Target threshold reference line (where the metric has one)
  - **By Specialty** panel stays (it's not time-series; useful as is).

The 4 summary cards at the top stay — they're complementary to the
trend panels.

## Acceptance criteria

- [ ] AC-1: `GET /admin/metrics/timeseries?from=2026-05-12&to=2026-05-26`
  returns a `MetricTimeseriesResponse` with `bucket == "day"` and one
  bucket per calendar day in the range (15 buckets, even if some are
  empty — empty days carry `session_count: 0` and all metrics null).
  Verified by `pytest backend/tests/unit/test_metrics_timeseries.py::test_timeseries_returns_one_bucket_per_day`.
- [ ] AC-2: With `clinician_id=<uuid>` filter, the response only includes
  rows whose `pilot_metrics.clinician_id` matches. Verified by
  `pytest backend/tests/unit/test_metrics_timeseries.py::test_timeseries_filters_by_clinician`.
- [ ] AC-3: A day with one session whose `session_completeness=true`
  reports `session_completeness: 100.0` in that bucket. Verified by
  `pytest backend/tests/unit/test_metrics_timeseries.py::test_timeseries_session_completeness_is_percentage`.
- [ ] AC-4: A day with two sessions averages the numeric metrics
  arithmetically. Verified by
  `pytest backend/tests/unit/test_metrics_timeseries.py::test_timeseries_averages_numeric_metrics`.
- [ ] AC-5: A non-EVAL_TEAM, non-ADMIN call returns 403. Verified by
  `pytest backend/tests/unit/test_metrics_timeseries.py::test_clinician_cannot_access_timeseries`.
- [ ] AC-6: Frontend dashboard renders 8 sparkline panels after the
  switch — confirmed manually once deployed.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - `require_role(UserRole.EVAL_TEAM, UserRole.ADMIN)` — same gate as
    `GET /admin/metrics`
  - `PilotMetricsModel` already persists each metric per session
  - `metrics.py` already lives under `app/api/v1/admin/` — extend it,
    don't fork
  - SQLAlchemy's `func.date_trunc('day', col)` for the bucket key
- **New helper introduced?**: One — `pilot_metrics_repo.get_timeseries`
  (currently no `pilot_metrics_repo` exists; sessions.py inlines its
  one query). This is the **third** time we'd inline a pilot_metrics
  query (admin/metrics.py + sessions completeness join + this); time
  to extract per DRY.
- **iOS UI tasks only**: N/A — backend + web only.

## Out of scope

- Chart library integration (recharts / ECharts) — frontend uses CSS
  sparklines in this PR. Filed as `WEB-CHARTS-LIB` follow-up if
  someone decides we need polished interactivity.
- Hourly / weekly bucket variants (the `bucket` param hardcoded to
  `"day"` in this PR; the enum exists in the response shape so a
  later PR can add `"hour"` / `"week"` without breaking clients).
- Per-clinician breakdown panels (one set of 8 panels for the whole
  pilot in this PR; clinician filter is supported in the API).
- Per-specialty time-series (one set of 8 panels for the whole pilot;
  specialty filter is supported in the API).
- Real-time / WebSocket updates.

## Test plan (executable)

1. `cd backend && python3 -m pytest tests/unit/test_metrics_timeseries.py -v`
   (expect the 5 AC tests to pass)
2. `cd backend && python3 -m pytest tests/unit/ -q`
   (expect 241 + new = 246 passing)
3. `cd web && npx next lint` (expect 0 errors)
4. CI's `build` + `lint` + `test` jobs must turn green on the PR

## Security implications

- Endpoint gated `require_role(EVAL_TEAM, ADMIN)` — same boundary as
  existing `/metrics`. Compliance officer + clinical_admin still don't
  see metrics; that's intentional per the §Role Access Matrix in the
  spec.
- No PHI in the aggregate response — only averages over numeric
  metric values + counts. Clinician_id appears in filters but not
  the bucket payload.
- No new audit events (read-only endpoint).
- No new AI calls, no new secrets, no new env vars.
- Postgres window scan cost: at pilot scale (≤ 5 clinicians × ≤ 50
  sessions/day × 30-day window = 7,500 rows max) the GROUP BY is
  trivial. Add an index on `pilot_metrics.created_at` if a future
  load test shows scan time > 50ms; index is **not** part of this PR.

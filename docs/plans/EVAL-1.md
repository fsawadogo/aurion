# Plan — EVAL-1 (eval compare lab)

## Task

Add a **run-comparison** surface to the existing admin/eval lab: pick a session, select 2+ of its note **versions** ("runs"), and see them side by side — the settings each was generated with, the note, and objective metrics. This is the eval receipt for Cohort 7: same input, flag off vs on, frames vs no-frames.

## Decisions (Uzziel, 2026-07-20)

- **Run creation = flip the global flag between runs.** No per-session flag override plumbing. The admin generates run A (flag off), flips the Feature Flag, generates run B (flag on); the page RECORDS which flags/template/frames each run used. This is why **provenance capture** is the core enabler.
- **Scope = versions within a session.** Pick a session → compare its versions. (Cross-session compare is a later option.)

## What exists (audit, quote-backed)

- The eval lab is **view + human-score only** (`admin/eval.py`, `EvalDetailClient.tsx`) — it loads only the LATEST note version and can't compare.
- **Runs already exist as note versions.** `NoteVersionModel` stores `provider_used, stage, specialty, completeness_score, content(note JSON), is_approved, created_at`. History query `note_repo.get_all_versions` exists but is **NOT exposed via HTTP**.
- **No per-version provenance** — a version does NOT record `template_key` or the flag state that produced it. This is the gap the "record which flags each run used" decision requires.
- **Deterministic per-note metrics** already coded in `scripts/grounded_synthesis_eval.py::compute_grounding_metrics` (claim count, grounding rate, section completeness) — reuse, no model call.
- **Claim-level diff** in `web/lib/portal-preview-diff.ts` — reuse for the two-run diff.

## Approach

### Backend

1. **Provenance capture.** Add `settings_snapshot: JSON | null` to `note_versions` (Alembic migration; nullable so old rows read as "unknown"). Populate at version creation with the settings live at generation time:
   `{ template_key, custom_template_id, template_engine_enabled, grounded_synthesis_enabled, detail_level, stage }`.
   Captured where `NoteVersionModel` is created (`note_gen` create-version path) by reading `get_config().feature_flags` + the resolved template. Never PHI — flags + a template key.
2. **Metrics helper.** Lift `compute_grounding_metrics` into an importable module (`app/modules/eval/metrics.py`) so both the CLI script and the endpoint use ONE implementation. Per-version: `claim_count, grounding_rate, ungrounded_claims, section_completeness`.
3. **Endpoint** — `GET /admin/eval/sessions/{session_id}/runs` (EVAL_TEAM + ADMIN, owner rules as the eval routes). Returns every version as a "run": `version, stage, provider_used, completeness_score, created_at, settings_snapshot, metrics, sections(note JSON)`. Reuses `get_all_versions`.

### Web

4. **Compare page** — extend `/eval`. From a session, a **run picker** (checkbox list of its versions with a one-line settings summary), then a **side-by-side** of the selected runs: a settings/metrics header row per run + the note columns. Two-run selections also show the claim-level diff (`portal-preview-diff`). Admin/eval-gated like the rest of `/eval`.

## Acceptance criteria

- [ ] **AC-1:** a new note version records its `settings_snapshot` (flags + template) at creation — `test_eval_run_provenance.py`
- [ ] **AC-2:** old versions (null snapshot) don't crash the endpoint or page — degrade to "settings unknown"
- [ ] **AC-3:** `GET /admin/eval/sessions/{id}/runs` returns all versions with metrics, EVAL_TEAM/ADMIN gated, 403 for others — `test_eval_runs_endpoint.py`
- [ ] **AC-4:** metrics match `compute_grounding_metrics` (one implementation, shared with the CLI) — `test_eval_metrics_shared.py`
- [ ] **AC-5:** the page lets an admin select 2+ runs of a session and renders them side by side with settings + metrics + note — `EvalCompare.spec.tsx`
- [ ] **AC-6:** full `tests/unit/` + `vitest` green; ruff + lint + build clean; migration up/down clean; zero iOS diff

## Out of scope

- **Per-session flag override** (a "Run" button that does on+off without a global flip) — deliberately deferred; the flip-and-record path is the agreed MVP.
- Cross-session run comparison.
- LLM-judged quality scores (the human scoring panel already exists; this adds objective metrics + the note diff).
- Changing note generation itself.

## Security / safety

- **Admin/eval only** — same `require_role(EVAL_TEAM, ADMIN)` as the eval routes; no new public surface.
- **No PHI in `settings_snapshot`** — it holds feature flags + a template key/id, never patient data.
- **Global-flag flip is dev-only** and the admin's deliberate action; the page just records the resulting per-run state. Nothing here changes what the flag does in prod.
- **Metrics are deterministic** — computed from the stored note JSON + transcript ids, no model call, no new AI cost.

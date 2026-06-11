## Task
OV-1 — Denormalize provider attribution onto eval_scores (#74 prerequisite)

## Why
Issue #74 (quality A-B compare) needs eval scores joinable to the provider
that generated the scored note. The post-MVP audit: "denormalize
provider_used/model_name into eval_scores — do the migration first, it's
cheap now and painful later." Doing it before eval volume grows means
every future score carries attribution from day one.

## Approach
- models: `EvalScoreModel.provider_used` (String(50), nullable) +
  `model_name` (String(128), nullable).
- migration 0036: add both columns; backfill `provider_used` from each
  session's latest note version (one UPDATE..FROM DISTINCT ON; pilot scale).
- repository `upsert_score`: optional `provider_used`/`model_name` params,
  persisted like the spec-aligned fields.
- route: resolve `provider_used` via `note_repo.get_latest_version`
  (DRY-listed helper) at submit time; model_name stays None until usage
  records carry it.

## Acceptance criteria
- [ ] AC-1: upsert_score persists provider_used when passed; None keeps
      NULL — pytest tests/unit/test_eval_persistence.py
- [ ] AC-2: score-submit route stamps the latest note version's
      provider_used — pytest (route-level with mocked repo)
- [ ] AC-3: migration 0036 upgrades cleanly (CI alembic upgrade head on
      deploy; chain head 0035→0036 verified by alembic heads)
- [ ] AC-4: full backend unit suite green

## DRY / SOLID check
- Reuse: `note_repo.get_latest_version` (DRY list), the migration-0004
  nullable-column precedent on this very table, upsert ON CONFLICT shape.
- New helper introduced?: no.
- iOS: n/a.

## Out of scope
- The /compare-quality endpoint (OV-3) and UI (OV-4).
- Backfilling model_name (no source column on note versions today).

## Test plan (executable)
1. cd backend && python3 -m pytest tests/unit/test_eval_persistence.py -q
2. cd backend && python3 -m pytest tests/unit -q
3. cd backend && python3 -m alembic heads → single head 0036

## Security implications
None: provider names are non-PHI config values already stamped on notes;
no new read surface; audit unchanged (EVAL_SCORE_SUBMITTED already fires).

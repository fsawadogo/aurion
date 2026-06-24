## Task
ps-01 (#514) — Prompt Studio data model + migration.

## Why
Foundation for the Prompt Studio epic (#521). The global prompts that drive
note quality live only in code (`app.modules.prompts.registry`) with no
versioning or admin edit path. This adds the storage for admin-authored,
versioned, rollout-staged prompts — separate from the per-clinician
`prompt_overrides` table. Everything else in P0 (#515–#520) depends on it.
Spec: `docs/plans/prompt-studio-spec.md` → Technical notes / R4.

## Approach
Three append-only-friendly tables + one Alembic migration (`0042`, revises
`0041`), mirroring the `prompt_overrides` / `video_import_jobs` conventions.
- `studio_prompts` — named admin candidate bound to a job (`job_id` =
  registry key, not an FK).
- `studio_prompt_versions` — immutable versions; `UNIQUE(studio_prompt_id,
  version_no)` keeps the sequence monotonic.
- `prompt_publications` — append-only rollout; `superseded_at IS NULL` =
  active; `scope`/`target_role` stored as VARCHAR carrying
  `PublicationScope`/`UserRole` values.
New `PublicationScope` enum in `app/core/types.py`. Ships inert — no writer
until ps-03/ps-05. No ORM relationships (matches existing models).

## Acceptance criteria
- [ ] AC-1: `studio_prompts`, `studio_prompt_versions`, `prompt_publications`
  exist as ORM models with the documented columns, verified by
  `tests/unit/test_prompt_studio_models.py`.
- [ ] AC-2: version sequence is collision-free — `UNIQUE(studio_prompt_id,
  version_no)` present, verified by `test_version_sequence_is_unique_per_prompt`.
- [ ] AC-3: deleting a studio prompt cascades to its versions, verified by
  `test_studio_prompt_versions_cascade_from_parent`.
- [ ] AC-4: migration `0042` applies and reverses cleanly on Postgres,
  verified by `alembic upgrade head` then `alembic downgrade -1`.
- [ ] AC-5: `ruff check backend/` and `pytest tests/unit/test_prompt_studio_models.py`
  pass.

## DRY / SOLID check
- **Existing helpers to reuse**: column/timestamp conventions from
  `PromptOverrideModel`; migration shape from `2026_06_19_0041_video_import.py`;
  `gen_random_uuid()` PK default already used repo-wide.
- **New helper introduced?**: No helper — three data models + one enum. The
  enum is a new shared type in `core/types.py` (the canonical home), not a
  duplicated literal.
- **OCP**: `scope`/`target_role` are VARCHAR carrying enum values, so a new
  scope is a code change, not a schema migration.

## Out of scope
Resolution logic (ps-02), API/CRUD (ps-03), test endpoint (ps-04), publish +
flag/role gate + audit events (ps-05). No rows are written by this PR.

## Test plan (executable)
1. `./.venv/Scripts/ruff.exe check backend/app/core backend/alembic backend/tests/unit/test_prompt_studio_models.py`
2. `./.venv/Scripts/python.exe -m pytest tests/unit/test_prompt_studio_models.py -v`
3. `alembic upgrade head` then `alembic downgrade -1` against the dev Postgres → both succeed.

## Security implications
No PHI. Prompt `text` is sensitive (authored phrasing) but not patient data;
it never enters logs or audit rows — only its length will, in later PRs. No
audit events added here. No new AI prompt text. Tables ship inert.

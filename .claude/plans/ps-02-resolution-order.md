## Task
ps-02 (#515, part of MVP #524) — prompt resolution order: make an admin-published prompt take effect.

## Why
For "share a prompt to the team/clinicians" (#524) to mean anything, a published
prompt must actually drive note generation. Today `assemble_prompt` only knows
the per-physician override → registry default. This inserts the **publication**
tier between them, so a prompt an admin authored + published reaches clinicians
who haven't set their own override. Spec: `docs/plans/prompt-studio-spec.md` → R7.

## Approach
Extend `app/modules/prompts/assembly.py`:
- `assemble_prompt` resolves, most specific first: (1) personal override
  (`prompt_overrides`, unchanged) → (2) active `prompt_publications` for the job
  matching the clinician, `SELF` → `ROLE` → `ALL` → (3) registry default.
- `_select_published(rows, owner_id, role_value)` — **pure** precedence selector
  (no DB), mirroring the existing `_select` split so the rule is unit-testable.
- `_get_published_prompt(db, owner_id, prompt_id)` — reads active publications
  (`superseded_at IS NULL`) joined to their version text + the clinician's role,
  then applies the selector. Models imported at function scope (matches the
  `assemble_prompt_for_session` pattern that keeps `app.core.models` off the
  prompts import path at startup).
- **Decision baked in (reversible):** personal override outranks an admin
  publication — the documented default; flagged for Faical.

## Acceptance criteria
- [ ] AC-1: SELF > ROLE > ALL precedence, verified by
  `tests/unit/test_prompt_resolution_precedence.py` (pure, no DB).
- [ ] AC-2: a published `ALL` prompt is returned by `assemble_prompt` for a
  clinician with no override, verified by `tests/integration/test_prompt_resolution.py`.
- [ ] AC-3: a personal override beats an active publication (override wins),
  same file.
- [ ] AC-4: a `SELF` publication reaches only its target user; others fall to
  the registry default; a `ROLE` publication reaches only that role.
- [ ] AC-5: registry default still returned when no override and no publication.
- [ ] AC-6: `ruff check` + the two test files pass against the dev Postgres.

## DRY / SOLID check
- **Existing helpers reused**: `_get_user_prompt`, `_select` pattern, the
  `select(...)` query style, the integration DB fixtures pattern from
  `tests/integration/test_prompt_overrides.py`.
- **New helper introduced?**: `_select_published` (pure) + `_get_published_prompt`
  — a new tier, not a duplicate; the pure/async split matches `_select` /
  `assemble_prompt`. OCP: a new scope is handled by `PublicationScope` + the
  selector, no branching elsewhere.

## Out of scope
The create/save API (ps-03), publish endpoint (ps-05), web UI (ps-06), and the
transparency-page `active_prompt` projection (`select_active_prompt` stays
override-only for now — generation is what must reflect a shared prompt).

## Test plan (executable)
1. `ruff check backend/app/modules/prompts/assembly.py backend/tests/unit/test_prompt_resolution_precedence.py backend/tests/integration/test_prompt_resolution.py`
2. `python -m pytest tests/unit/test_prompt_resolution_precedence.py tests/integration/test_prompt_resolution.py -v` (Postgres on :5434 up)

## Security implications
No PHI. No new logging of prompt text. No audit events (publish writes those in
ps-05). Published prompt text is the same sensitivity class as the per-physician
override — never logged. The descriptive-mode boundary on published text is
enforced at save/publish time (ps-03/ps-05 reuse `validate_user_prompt`), not
here. Personal-override-wins preserves the existing physician-signoff guarantee.

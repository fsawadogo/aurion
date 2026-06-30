# Plan — tpl-central-1-fork (backend): duplicate a Library template into My Templates

## Task
#575 (Phase 1 of #574). Backend half: a clinician forks a Library template
(their own OR a shared org template) into a NEW template they own, then edits the
copy. This is the "edit a library template into theirs → their source of truth"
move. (Web My/Library split + fork button = follow-up PR; forking a built-in
specialty template by key = fast-follow.)

## Why
Today a clinician can't clone a shared template into their own — they'd rebuild
it by hand (Agent map: "No duplicate/copy/fork function exists"). The data model
already separates owned vs shared (`CustomTemplateModel.owner_id` / `is_shared`,
models.py:412), and the prompt cascade already ranks an owned template above a
shared one (assembly.py:314), so a fork cleanly becomes the clinician's source of
truth. No iOS impact — iOS lists templates via `getCustomTemplates()`, so the
fork appears automatically.

## Approach
Pure reuse of the existing service.
- `custom_templates/service.py`:
  - `duplicate_into_owner(source_id, owner_id, db) -> Optional[CustomTemplateModel]`
    — `get_owned_or_shared(source_id, owner_id, db)` (forks own OR shared; a
    foreign *private* template stays unreadable → None → route 404); copy the
    content JSON; set a per-owner-unique key + a "(copy)" display name; persist
    via `create_for_owner(..., is_shared=False)` so the fork passes the same
    schema + descriptive-mode validation as any new template.
  - `_unique_copy_key(base, owner_id, db)` — `<key>-copy`, `-copy-2`… deduped via
    `_find_by_owner_and_key`, trimmed to the 50-char key cap.
  - `_copy_display_name(name)` — `"<name> (copy)"`, trimmed to 100.
- `api/v1/me.py`: `POST /me/custom-templates/{id}/duplicate` (CLINICIAN) → 201
  `CustomTemplateResponse`; 404 when the source doesn't resolve; mirrors the
  create route's `CUSTOM_TEMPLATE_CREATED` audit + commit.

## Acceptance criteria
- [ ] AC-1: `duplicate_into_owner` on a SHARED template → new row `is_shared=False`, `owner_id=caller`, content copied, key `<src>-copy`, name `"… (copy)"` — `tests/unit/test_custom_template_duplicate.py`.
- [ ] AC-2: forking when `<src>-copy` already exists → `<src>-copy-2` (per-owner dedupe) — same file.
- [ ] AC-3: source missing OR a foreign *private* template → returns None (route → 404) — same file.
- [ ] AC-4: `POST /me/custom-templates/{id}/duplicate` → 201 + `CustomTemplateResponse`; writes `CUSTOM_TEMPLATE_CREATED` — route test.
- [ ] AC-5: full backend unit suite green; ruff clean.

## DRY / SOLID check
- **Reuses**: `get_owned_or_shared`, `create_for_owner`, `_find_by_owner_and_key`,
  `_to_custom_template_response`, the `CUSTOM_TEMPLATE_CREATED` audit pattern. New
  helpers are SRP (key dedupe / name) + one service fn + one route.
- **OCP/SRP**: service owns the fork logic; route stays HTTP + audit only.

## Out of scope
- Web My Templates/Library split + "Save to My Templates" button (#575 web half — next PR).
- Forking a BUILT-IN specialty template by `template_key` (fast-follow; this PR is custom-UUID sources — which includes every admin Shared template, e.g. the lipo one).
- RBAC / Clinical Admin (#578).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_custom_template_duplicate.py -q`
2. `cd backend && python3 -m pytest tests/unit -q` → all pass
3. `ruff check` clean on touched files
4. N/A: iOS; docker boot (route/service change, unit-tested)

## Security implications
- CLINICIAN-scoped (`get_current_clinician`). `get_owned_or_shared` prevents
  forking another clinician's PRIVATE template (no cross-clinician read).
- Descriptive-mode preserved: `create_for_owner` re-runs `validate_user_prompt`
  on the forked `system_prompt`, so a fork can't smuggle in a non-descriptive
  prompt.
- Audit append-only (`CUSTOM_TEMPLATE_CREATED`, template metadata only — no PHI;
  same keys the create route already emits). No secrets / consent / masking.

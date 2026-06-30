# Plan — tpl-central-1b-fork-ui (web): My Templates vs Library + Duplicate button

## Task
#575 web half (epic #574). Turn the backend fork (PR #580, merged) into a real
UI: split the clinician Templates page into **My Templates** vs **Library**, and
add a **"Save to My Templates"** (Duplicate) button on Library rows that calls
the fork endpoint.

## Why
The backend fork (`POST /me/custom-templates/{id}/duplicate`) is live but has no
UI — the page (`web/app/portal/templates/page.tsx`) currently mixes owned +
shared in one list with a "Shared" badge, and a shared row's "Open" actually
404s (detail fetch is owner-scoped). This makes forking a real, clickable action
and fixes that dead "Open on shared" path. No iOS impact (web only).

## Approach
- `web/lib/portal-api.ts`: `duplicateMyCustomTemplate(id) -> CustomTemplate`
  (POST `/me/custom-templates/{id}/duplicate`), mirroring the existing
  create/delete helpers.
- `web/app/portal/templates/page.tsx`: split `list` into
  `mine = !is_shared` and `library = is_shared` (disjoint — `list_for_owner`
  returns only my-owned-private ∪ shared). Render two sections:
  - **My Templates** — existing rows (Open + Delete).
  - **Library** — rows with a single **"Save to My Templates"** button (no
    Open/Delete; shared rows aren't owner-editable). On click →
    `duplicateMyCustomTemplate` → `load()` → the fork appears at the top of My
    Templates.
- `web/messages/{en,fr}.json` (`TemplatesList`): add `myTemplatesHeading`,
  `libraryHeading`, `myTemplatesEmpty`, `libraryEmpty`, `saveToMine`,
  `duplicateError`, `duplicateAria`.

## Acceptance criteria
- [ ] AC-1: the page shows two labelled sections — My Templates (owned) and Library (shared) — split by `is_shared`.
- [ ] AC-2: Library rows show a "Save to My Templates" button; My Templates rows keep Open + Delete; Library rows show neither.
- [ ] AC-3: clicking Save to My Templates calls `duplicateMyCustomTemplate` and the fork then appears under My Templates (verified in vitest + live on localhost:3000).
- [ ] AC-4: `eslint` + `tsc --noEmit` clean; vitest green.

## DRY / SOLID check
- Reuses the existing row markup, `Button`/`Badge`/`Card`/`Modal`, the
  `humanizeError` + load() patterns, and the portal-api helper shape. New = one
  api fn + a row-render split. No new mechanism.

## Out of scope
- Forking a **built-in** specialty template by key (fast-follow).
- The admin System+Shared "Library" unification (#579).
- Navigating to the fork's editor on duplicate (could add later; for now the
  fork just appears under My Templates).

## Test plan (executable)
1. `cd web && npx vitest run tests/templates-list.spec.tsx` (new) + i18n parity spec
2. `cd web && npx eslint app/portal/templates/page.tsx lib/portal-api.ts` → clean
3. `cd web && npx tsc --noEmit` → clean
4. Live: `localhost:3000` → log in `perry@creoq.ca`/`perry` → Templates → see My Templates vs Library + a working Duplicate button.

## Security implications
- Web-only; all enforcement stays server-side (the fork endpoint is
  CLINICIAN-scoped + `get_owned_or_shared`). No new PHI surfaced (template
  metadata only). No secrets/auth changes.

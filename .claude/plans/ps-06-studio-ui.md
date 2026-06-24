## Task
ps-06 (#519, part of MVP #524) — Prompt Studio web UI: library + create + publish.

## Why
The last slice of #524 — makes create & share clickable in the portal. An ADMIN
page to author/upload a prompt, save versions, and publish to a cohort, against
the ps-03/ps-05 API. Spec → R2/R3/R8 (web). Web portal only.

## Approach
- `web/lib/api.ts`: 6 client functions + types for the studio endpoints
  (jobs / list / detail / create / save-version / publish).
- `web/app/portal/admin/prompt-studio/page.tsx`: library list + selected-prompt
  detail (current version, new-version editor, publish scope picker) + a create
  modal. Reuses `Modal` / `Button` / `Card` / `Badge` / `PageHeader` /
  `LoadingSkeleton`, `fetchWithAuth`, `humanizeError`, and a `parseStudioError`
  mirroring the prompts page's validator-400 parse.
- Sidebar nav item (ADMIN-only) + i18n (`AdminPromptStudio` namespace +
  `Sidebar.nav.promptStudio`) in en + fr.
- vitest: renders, lists, create-from-modal, publish-to-ALL.

The page is flag + role gated server-side (ps-05); when the flag is off the API
403s and the page shows the error state. The nav item is ADMIN-only.

## Acceptance criteria
- [ ] AC-1: lists authored prompts + a "Create new prompt" button; empty /
  loading / error states (`renders the header and lists authored prompts`).
- [ ] AC-2: create modal — name + job (prefills the text from the job's current
  default) + text → POST; validator 400 shown inline
  (`creates a new prompt from the modal`).
- [ ] AC-3: selected prompt — current version, save-new-version, publish (scope
  SELF / ROLE / ALL, role select for ROLE) (`publishes the selected prompt's
  latest version to ALL`).
- [ ] AC-4: `eslint` clean; `vitest` green; en/fr parity holds (AIPrompts
  parity spec still passes alongside the new namespace).

## DRY / SOLID check
- **Reused**: `fetchWithAuth` / `ApiError` / `humanizeError`, the UI component
  library, the page + test patterns from `app/portal/prompts/page.tsx` and
  `tests/AIPromptsPage.spec.tsx`, the validator-400 parse shape.
- **SRP**: page = data + layout; `CreatePromptModal` + `PromptDetail` are
  presentation sub-components.

## Out of scope
The testing / A-B workbench (ps-07), version-diff, panel testing, a "which
version is live" indicator (the thin list API doesn't return it yet),
session-pull, archive/unpublish.

## Test plan (executable)
1. `npx eslint app/portal/admin/prompt-studio/page.tsx lib/api.ts components/Sidebar.tsx tests/PromptStudioPage.spec.tsx`
2. `npx vitest run tests/PromptStudioPage.spec.tsx tests/AIPromptsPage.spec.tsx`

## Security implications
ADMIN-only (nav + the API's router-level gate). No PHI. The descriptive-mode
gate is enforced server-side at save (ps-03); the page surfaces its 400 inline.
No prompt text logged. The whole surface is flag-gated server-side (ps-05) — the
page shows a clean error when the API 403s.

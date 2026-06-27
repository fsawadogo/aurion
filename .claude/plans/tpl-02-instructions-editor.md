# tpl-02 — web template editor "AI instructions" field

Step 1's web half: lets a clinician (and, via the same component, admin) **set** a
template's note-gen instructions in the editor — the field that backs the
tpl-01 backend `Template.system_prompt`.

## Change (web only)

- **`types/index.ts`** — `TemplateDefinition.system_prompt?: string | null`.
- **`components/portal/TemplateSectionEditor.tsx`** — the one shared editor behind
  both create (`/templates/new`) and edit (`/templates/[id]`):
  - `blankTemplate()` seeds `system_prompt: ""`.
  - `normalizeTemplate()` trims it; empty/whitespace → `null` (mirrors the
    backend "blank = no instructions" gate).
  - A new optional "AI instructions" textarea (after the metadata grid, before
    Sections), wired via `setMeta`, `data-testid="template-system-prompt"`.
- **i18n** — `TemplateEditor.aiInstructions` / `…Placeholder` / `…Hint` in en + fr.

No API-client change (`createMyCustomTemplate`/`updateMyCustomTemplate` already
POST/PATCH the whole `{ template }`). No new error handling — the backend's
descriptive-mode rejection is a flat `detail` string already surfaced by the
existing `humanizeError` red banner.

## Scope held tight
- AI conversational builder: untouched (no field editing; would need backend
  authoring-session changes).
- Full Example/Structure clean redesign + library cleanup: deferred (the mockup
  is the target; not needed to set/test instructions).

## Tests
- `normalizeTemplate` trims / nulls system_prompt; `blankTemplate` seeds it;
  the editor textarea edits `value.system_prompt`.
- eslint clean; vitest green (19 incl. i18n en/fr parity + 7 editor tests).

## Verify → `/code-review` → PR. Next: tpl-03 upload template picker (step 2).

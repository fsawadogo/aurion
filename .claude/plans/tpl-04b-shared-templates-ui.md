# tpl-04b — admin Shared-templates page (web, PR2)

The admin UI for shared/org templates — the Prompt-Studio-style surface that
finishes "admin authors → clinicians find + use" in the portal (backend = #540).

## Change (web only)
- **`lib/api.ts`** — `listSharedTemplates` / `createSharedTemplate` /
  `deleteSharedTemplate` → `/admin/shared-templates` (#540), returning the
  existing `CustomTemplate` shape.
- **`app/portal/admin/shared-templates/page.tsx`** (new) — library list of shared
  templates (name, key, version, delete) + a "New shared template" flow that
  reuses the shared **`TemplateSectionEditor`** (so an org template carries
  structure **and** AI instructions, tpl-02) → `createSharedTemplate`.
- **`Sidebar.tsx`** — ADMIN nav entry "Shared Templates" (`Share2` icon).
- **i18n** — `AdminSharedTemplates` namespace + `Sidebar.nav.sharedTemplates`
  (en + fr).

No edit endpoint in #540, so the page is **create / list / delete** (edit =
delete + recreate for now). Clinician side needs nothing — shared templates
already surface in their Templates library (Shared badge) + the upload/visit
pickers, and apply at note-gen (verified: `_resolve_stage1_template` loads by id
via unscoped `get_by_id`; instructions via tpl-01).

## Tests
- vitest: lists shared templates; creates one through the editor (asserts the
  POST body); deletes one.
- eslint + typecheck clean; i18n en/fr parity green.

## After this + #540 deploy — the full workflow is live
Admin → **Shared Templates** → author (structure + AI instructions) → share →
every clinician sees it in **Templates** (Shared badge) and can **pick it** on
record (via the visit-type binding) or on **upload** → the note is generated with
that template's structure + instructions.

## Deferred (optional)
Per-role audience scoping + template versioning/diff (Prompt Studio has these;
shared templates are share-to-all, single-version for now).

## Verify → self-reviewed → PR.

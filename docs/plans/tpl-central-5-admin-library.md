# Plan — tpl-central-5 (#579): unify System + Shared Templates into one admin Library

## Task
#579 (epic #574), lane-web, **Step 1 (UI only, no data change)**. The admin
portal has two global-template surfaces split only by storage mechanism —
System Templates (built-in, override by key) and Shared Templates (org-custom by
UUID). Merge them into one **Library** admin view with two sections. **Stacked
on #578** (inherits the CLINICAL_ADMIN nav role).

## Approach (extraction, not copy-paste)
- Extract each page body into a reusable component (no behaviour change):
  - `web/components/portal/AdminSystemTemplatesSection.tsx`
  - `web/components/portal/AdminSharedTemplatesSection.tsx`
  (No PageHeader / page-padding — the host supplies the heading. Shared's "New"
  action moves into a section toolbar so it sits atop its list in either host.)
- The two former pages become **thin wrappers** (PageHeader + Section) — keeps
  their existing routes AND their existing specs green (the specs render the
  page, which renders the same component).
- New `web/app/portal/admin/library/page.tsx`: PageHeader + two `<section>`s
  (Built-in / Org-custom) composing the two section components.
- `Sidebar.tsx`: replace the `systemTemplates` + `sharedTemplates` nav entries
  with one `library` entry → `/portal/admin/library`, roles = union
  `[ADMIN, COMPLIANCE_OFFICER, CLINICAL_ADMIN]`. Drop the now-unused `Share2`
  icon import. Prompt Studio stays its own entry.
- i18n: new `AdminLibrary` namespace (eyebrow/title/description + the two
  headings) + `Sidebar.nav.library`; drop the orphaned `systemTemplates` /
  `sharedTemplates` nav keys. en + fr in lockstep. The `AdminTemplates` /
  `AdminSharedTemplates` namespaces stay (reused by the sections).
- Update the #578 `SidebarClinicalAdmin.spec` to assert the consolidated
  "Library" nav item instead of the two former labels.

## Acceptance criteria
- [ ] AC-1: one admin Library page lists + edits both built-in (override) and shared-custom templates.
- [ ] AC-2: existing System Templates + Shared Templates behaviour preserved (their specs still pass through the wrappers).
- [ ] AC-3: one consolidated nav entry; CLINICAL_ADMIN/ADMIN/COMPLIANCE see it.
- [ ] AC-4: web test (Library composition) + eslint/tsc clean; full vitest green.

## DRY / SOLID
Pure reuse: the section components are the single source of the two experiences;
the standalone pages and the Library both render them. No logic duplicated, no
API/data change.

## Out of scope
- Step 2 storage convergence (System override vs Shared UUID) — later.
- Deleting the old routes (kept as wrappers for back-compat; nav points only at Library).

## Test plan
1. `vitest run tests/AdminLibraryPage.spec.tsx` (new) + the existing `AdminTemplatesPage` / `SharedTemplatesPage` specs (must still pass via wrappers) + `SidebarClinicalAdmin` (updated) + `i18n-bootstrap` (parity).
2. `eslint` (new components + pages + Sidebar + specs) + `tsc --noEmit` → no new errors.
3. Live: `localhost:3000` → `/portal/admin/library` renders both sections.

## Security implications
- Web-only; enforcement stays server-side (the two backend admin routers are
  unchanged and already gated). No new data surface. No secrets.

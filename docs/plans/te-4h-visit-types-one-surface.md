## Task

TE-4h — one surface for the clinician's visit-type → template mapping. The
default template moves INSIDE each visit-type accordion panel; the flat
7-dropdown clinician list, the doubled headings, and the stale "manage in My
Profile" footer go away. Admin org-default list untouched.

## Why

Uzziel 2026-07-29, from the live page: the Templates → Visit Types tab shows
two look-alike surfaces (flat defaults + accordion) editing the same
`contexts_per_visit_type` map — and post-#699 both offer the identical option
list, so the one real difference (`is_default`) is invisible. Confirmed
defect: the accordion has zero `is_default` awareness, so a default set up top
renders as a phantom context row below — counted in the badge, deletable, and
deleting it silently clears the default. Approved mockup: one accordion per
visit type holding "Default template" + contexts, collapsed rows summarizing
"Default: {name} · N contexts". Marie's encounter flow (visit type → optional
context → template resolves; override before/after recording) is untouched —
this is config-UX only, the last UI piece of the Cohort 7 engine.

## Approach

**`VisitTypeContextsEditor.tsx` learns about the default** (it is the single
accordion both My Profile and the Templates tab embed — both doors gain the
default control, per the keep-Profile-synced decision):

- Per visit type, split the list: `defaultCtx = list.find(c => c.is_default)`,
  `contexts = list.filter(c => !c.is_default)`.
- New "Default template" `<select>` at the top of the expanded panel.
  Value = `defaultCtx?.template_ref ?? defaultCtx?.template_key ?? ""`.
  Options: "" (Use my specialty default) + Custom templates optgroup + the two
  existing guard placeholders reused verbatim (`legacySpecialtyTemplate` for a
  legacy built-in pin, `customUnavailable` for a stale ref — the stale-ref
  guard on the DEFAULT select is new coverage the #699 review asked for).
- `setDefaultTemplate(vt, value)`: "" → drop the `is_default` row (list empty →
  key dropped, mirroring `withClinicianDefault`); custom id → upsert
  `{id: defaultCtx?.id ?? newContextId(), label: defaultCtx?.label ||
  visitTypeLabel(vt), template_ref: id, template_key: null, is_default: true,
  description: defaultCtx?.description ?? null}` — id/label/description
  preserved on re-pick.
- Collapsed header gains a summary: "Default: {custom display name |
  Specialty default | legacy label}"; the count badge switches to
  `contexts.length` (named only). The 30-cap check stays on the FULL list
  (mirrors the backend cap). Add-context dup-validation stays against ALL
  labels (backend validates the full list; a hidden-row dup 422 would be
  worse than a visible "already on the list").
- Editor `description` copy updated to mention the default (EN+FR).

**`VisitTypesTab.tsx` slims to: admin flat org list XOR the accordion.**

- Clinician branch: delete the flat `<ul>` of `renderSelect` calls, the
  duplicated `visitsContextsTitle`/`visitsContextsHint` heading block, and the
  stale `visitsProfileSubcontexts`/`visitsGoToProfile` footer. Keeps: the
  accordion + the one Save button + dirty tracking (draft model unchanged —
  the TE-4f single-save race guarantee holds by construction).
- Dead code falls out: `clinicianValue`, `withClinicianDefault`,
  `onClinicianChange`, and the TE-4g `legacyBuiltin`/`isBuiltinValue`
  placeholder in `renderSelect` (it was clinician-only; the guard now lives in
  the editor's default select). `renderSelect` returns to an admin-only shape.
- i18n: remove now-unused `TemplatesList` keys (`visitsContextsTitle`,
  `visitsContextsHint`, `visitsProfileSubcontexts`, `visitsGoToProfile`,
  `visitsMineGroup`, `visitsClinicianHint`); add `Profile.contexts.default*`
  keys (label, hint, aria, summary, summary-specialty). EN and FR in the same
  commit.

## Acceptance criteria

- [ ] AC-1: clinician Templates → Visit Types renders NO flat default list —
  one accordion + one Save (VisitTypesTab.spec).
- [ ] AC-2: default select per panel — picking a custom upserts the
  `is_default` row (id preserved on re-pick); picking "" (specialty default)
  drops it from the map (VisitTypeContexts.spec, replaces the TE-4g
  tab-level tests).
- [ ] AC-3: a default still pinned to a built-in `template_key` renders the
  visible "Specialty template (re-pick)" option, value preserved.
- [ ] AC-4: a default whose `template_ref` no longer resolves renders the
  "Custom template (unavailable)" option — not a blank select.
- [ ] AC-5: `is_default` rows never render as context rows; the badge counts
  named contexts only.
- [ ] AC-6: collapsed header shows the default summary (custom name /
  specialty default / legacy label).
- [ ] AC-7: admin view unchanged — flat org list with built-ins optgroup, no
  accordion, no Save (existing admin tests stay green untouched).
- [ ] AC-8: exactly one heading over the accordion; the Profile footer link is
  gone (VisitTypesTab.spec).
- [ ] AC-9: My Profile still renders the editor (now with the default
  control) — Profile specs green/adjusted.
- [ ] AC-10: EN/FR parity — added and removed keys in both catalogs
  (i18n-bootstrap green).
- [ ] AC-11: full `npx vitest run` green; `npx next lint` clean;
  `npm run build` exit 0.

## DRY / SOLID check

- **Existing helpers reused**: `newContextId`, `setContexts`/`updateContext`
  plumbing (default upsert goes through them), `legacySpecialtyTemplate` +
  `customUnavailable` + `defaultTemplate` strings, `visitTypeLabel`,
  the draft/save model in the tab.
- **New helper introduced?**: `setDefaultTemplate` in the editor — not a copy
  of `withClinicianDefault`, its replacement (the tab's copy is deleted in the
  same diff; net helpers for this behavior: one).
- **iOS UI tasks only**: n/a — web-only; server contract and iOS untouched.

## Out of scope

- Admin org tier (option B) and backend pin retirement (option C, chip
  task_90a5d9aa).
- The owned-vs-all custom-template option mismatch between the Profile door
  (owned only) and the Templates door (all mine) — pre-existing, both for
  context pins and now defaults; needs its own decision.
- Stale-ref placeholder for the ADMIN org select (the remainder of chip
  task_8882a9c7 after AC-4 covers the clinician default).
- Relabelling "Use my specialty default" to name the specialty.

## Test plan (executable)

1. `cd web && npx vitest run tests/VisitTypeContexts.spec.tsx tests/VisitTypesTab.spec.tsx` → new + reworked tests pass.
2. `cd web && npx vitest run` → full suite green (incl. Profile + i18n-bootstrap).
3. `cd web && npx next lint` → clean.
4. `cd web && npm run build` → compiled + static export, exit 0.

## Security implications

None new. Context labels and custom-template display names can be PHI — they
stay render-only (no logging), unchanged. Same single PUT to
`updateMyProfile`; no new endpoints; server-side resolution
(`resolve_context_template_key`) byte-identical. The change strictly REDUCES
silent-failure surface (phantom-row delete can no longer clear a default; the
default select gains the stale-ref guard).

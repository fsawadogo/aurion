## Task

TE-4g — remove the 8 built-in specialty templates from the **clinician's**
per-visit-type default dropdown in Templates → Visit Types. The clinician's
menu becomes "Specialty default" + their own custom templates, matching what
TE-4e did to the note-review picker and the per-context editor.

## Why

TE-4e pulled built-in specialty templates out of the pickers so a clinician's
specialty template comes from their profile, not a hand-picked menu entry
(memory: `descriptive-mode-and-authored-templates`, `project-visit-type-template-map`).
It deliberately left `VisitTypesTab` alone (te-4e receipt: *"AC8 …
BUILT_IN_TEMPLATE_KEYS … kept for out-of-scope consumers (VideoImportClient,
VisitTypesTab)"*). The #696 review recorded the remainder as the deferred
"per-context built-in-pin retirement (VisitTypesTab still creates them)". This
slice closes the **clinician** half only — the smallest, web-only step.

## Approach

`web/components/portal/VisitTypesTab.tsx` — the flat default dropdown is drawn
by one shared `renderSelect`, used for both the admin org-default and the
clinician default. Add an `includeBuiltins` parameter:

- **admin** call → `includeBuiltins = true` (org tier unchanged — option B/C
  are out of scope);
- **clinician** call → `includeBuiltins = false`: no `visitsBuiltinGroup`
  optgroup, so the menu is `visitsSpecialtyDefault` ("") + the clinician's
  custom templates.

Silent-blank-select guard (the exact class of bug the #696 review caught in
`VisitTypeContextsEditor`): a clinician default already pinned to a built-in
`template_key` yields `clinicianValue = "builtin:<key>"`, which now matches no
option. When `!includeBuiltins && value.startsWith("builtin:")`, render one
visible placeholder `<option value={value}>` labelled with the existing
`Profile.contexts.legacySpecialtyTemplate` ("Specialty template (re-pick)")
string — reused, not duplicated — so the pin shows and stays re-pickable
(pick "" or a custom to move off it).

Files:
- `web/components/portal/VisitTypesTab.tsx` — `renderSelect` param + the two
  call sites + `useTranslations("Profile.contexts")` for the placeholder label.
- `web/tests/VisitTypesTab.spec.tsx` — clinician-menu assertions + legacy-pin
  placeholder test; admin built-in tests stay as the option-B guard.

No new message keys (reusing `legacySpecialtyTemplate`), so EN/FR parity is
untouched.

## Acceptance criteria

- [ ] AC-1: the clinician default dropdown offers only "Specialty default" +
  the clinician's custom templates — **no** built-in specialty options —
  verified by a VisitTypesTab.spec test asserting the built-in labels are
  absent and `custom:c1` is present.
- [ ] AC-2: the admin org-default dropdown **still** offers the built-ins —
  verified by the existing `sel.value === "builtin:orthopedic_surgery"` admin
  test staying green.
- [ ] AC-3: a clinician default already pinned to a built-in renders a visible
  "Specialty template (re-pick)" placeholder (not a blank `<select>`) and can
  be changed to specialty-default/custom — verified by a new test.
- [ ] AC-4: `npx vitest run` — full web suite green (incl. i18n-bootstrap EN/FR
  parity, unchanged here).
- [ ] AC-5: `npx next lint` clean and `npm run build` (static export) exits 0.

## DRY / SOLID check

- **Existing helpers to reuse**: `renderSelect` (extended with one param, not
  duplicated), `clinicianValue` / `withClinicianDefault` (unchanged),
  `BUILT_IN_TEMPLATE_KEYS` (still used by the admin branch), the
  `Profile.contexts.legacySpecialtyTemplate` message from TE-4e.
- **New helper introduced?**: no. One boolean parameter on an existing render
  function; the placeholder mirrors the TE-4e pattern already in the codebase.
- **iOS UI tasks only**: n/a — web-only.

## Out of scope

- **Option B** — removing built-ins from the **admin** org-default dropdown
  (would restrict org defaults to shared custom templates; product decision).
- **Option C** — backend no longer honouring stored built-in pins + a
  migration for existing ones. Not broken today: `resolve_context_template_key`
  re-validates every pin and degrades stale ones to the specialty default.
- `withClinicianDefault`'s `builtin` branch becomes unreachable from the
  clinician menu after this change — a `/simplify` candidate, left minimal here.
- Relabelling "Specialty default" to name the clinician's specialty
  (TE-4e-style "My specialty default (Plastic surgery)") — separate polish.

## Test plan (executable)

1. `cd web && npx vitest run tests/VisitTypesTab.spec.tsx` → clinician-menu +
   legacy-pin tests pass; admin built-in tests still pass.
2. `cd web && npx vitest run` → full suite green.
3. `cd web && npx next lint` → clean.
4. `cd web && npm run build` → compiled + static export, exit 0.

## Security implications

None. Pure client-side dropdown + i18n change. No PHI, no AI prompt, no audit
path, no consent gate. Server-side template resolution is untouched — any
existing built-in pin still resolves (and safely degrades) exactly as before.

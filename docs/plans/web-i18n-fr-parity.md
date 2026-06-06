# Plan — Portal FR i18n parity (closes #160)

Lane: `lane-web/i18n-fr-parity`
Issue: https://github.com/fsawadogo/aurion/issues/160

## Why

iOS ships full EN+FR parity. The web portal historically shipped EN-only
UI chrome — only the per-clinician *generated note* language was
configurable. With CREOQ/CLLC pilot physicians using EN+FR clinical
documentation, the portal chrome needs to match. Phase 9a punted the
next-intl integration to its own focused PR.

Foundation already exists on `main` after the static-export migration
(DEPLOY-WEB): `web/i18n/config.ts`, `web/i18n/LocaleProvider.tsx`, the
`<NextIntlClientProvider>` wrap in `app/layout.tsx`, and the
`LocaleSwitcher` component. Dashboard, prompts, admin/feature-flags,
and PatientDetailClient already use `useTranslations`. EN + FR
catalogs sit at 253 keys each, fully synced.

This PR completes the migration for the remaining 8 portal pages and
the Sidebar's mobile-menu aria labels.

## Approach

### Catalog updates

- Add 9 new namespaces to `web/messages/en.json`:
  `Sidebar.mobileMenu`, `Specialties`, `Macros`, `NotesList`,
  `Profile`, `Account`, `TemplatesList`, `TemplateNew`,
  `TemplateDetail`, `NoteReview`.
- Mirror every key in `web/messages/fr.json` with Québec French.
- `Specialties` namespace is shared so dropdowns across macros /
  profile / templates use the same translations.

### Page migrations

One namespace per page (`useTranslations("Macros")`, etc.) per the
DRY/SOLID gates in AURION-CODING-WORKFLOW §6c. Sub-namespaces (e.g.
`Macros.editor`, `NoteReview.actions`) keep keys scoped without
duplicating helpers across files.

Files touched:

- `web/app/portal/macros/page.tsx`
- `web/app/portal/notes/page.tsx`
- `web/app/portal/profile/page.tsx`
- `web/app/portal/templates/page.tsx`
- `web/app/portal/notes/[id]/NoteReviewClient.tsx`
- `web/app/portal/profile/account/page.tsx`
- `web/app/portal/templates/new/page.tsx`
- `web/app/portal/templates/[id]/TemplateDetailClient.tsx`
- `web/components/Sidebar.tsx` (mobile-menu aria labels only)

### Locale toggle UI

The `LocaleSwitcher` component already exists and renders in the
sidebar (compact variant). Per issue #160 we add an inline-variant
copy on `web/app/portal/profile/account/page.tsx` so users discover
it on the same screen as the generated-note-language picker.

### Out of scope

- Admin / compliance / eval pages (`admin/feature-flags`, `audit`,
  `eval`) stay EN. Issue body explicitly notes "admin chrome doesn't
  need FR".
- No `/[locale]/` route prefix — cookie-driven switching only per
  issue requirements; existing routes stay stable.
- No `Accept-Language` header parsing — under `output: "export"`
  there is no request-time hook to read it. The portal is
  authenticated; cookie + backend `ui_language` sync is the only
  resolution path.
- Per-clinician `output_language` (generated note language) stays a
  separate column / control. Conflating it with UI chrome locale is
  explicitly rejected — see CLAUDE.md memory entry.

## Acceptance criteria

- [ ] AC-1: EN catalog and FR catalog flatten to identical key sets,
      verified by `tests/i18n-bootstrap.spec.ts → catalog parity`.
- [ ] AC-2: All 8 hardcoded pages compile cleanly under
      `npx tsc --noEmit` with no new errors.
- [ ] AC-3: `LocaleSwitcher` writes `aurion-locale` cookie on click
      and calls `updateMyProfile`, verified by
      `tests/locale-toggle.spec.tsx`.
- [ ] AC-4: Sidebar mobile-menu aria labels translate via
      `t("mobileMenu.open" | "mobileMenu.close")`.
- [ ] AC-5: Static export (`npm run build`) succeeds (no
      `output: "export"` regression).
- [ ] AC-6: Existing migrated pages
      (`dashboard/`, `prompts/`, `admin/feature-flags/`,
      `patients/[identifier]/PatientDetailClient.tsx`) keep working
      — EN+FR catalogs already in parity for them.

## DRY / SOLID check

- **Existing helpers to reuse**: `useTranslations` from `next-intl`,
  `LocaleSwitcher` component, the shared `withIntl` test helper, the
  `LOCALE_COOKIE` / `isLocale` exports from `web/i18n/config.ts`.
  Page migrations do not introduce a new "translation helper"
  abstraction — `useTranslations(namespace)` is already the standard.
- **New helper introduced?**: No. Shared `Specialties` namespace
  replaces three local string-table copies (macros, profile,
  templates) and is the third extracted occurrence — meets the
  "third copy → abstract" gate.
- **iOS UI tasks only — `mobile-ios-design` consulted**: N/A
  (web-only PR).

## Security implications

- No new AI prompts, audit-log writers, or PHI surfaces.
- All catalog strings use placeholders (`{patientName}`,
  `{shortcut}`, `{count}`) — no sample PHI baked in.
- `LocaleSwitcher` already audited (#239 / #256 prior PRs).

## Test plan (executable)

1. `cd web && python3 -c "import json; en = json.load(open('messages/en.json')); fr = json.load(open('messages/fr.json')); assert set(_flatten(en)) == set(_flatten(fr))"`
   → no key drift between catalogs.
2. `cd web && npx tsc --noEmit` → no TS errors in `app/portal/**`,
   `components/Sidebar.tsx`, or new tests.
3. `cd web && npx vitest run tests/i18n-bootstrap.spec.ts` → all
   green.
4. `cd web && npx vitest run tests/locale-toggle.spec.tsx` → all
   green.
5. `cd web && npm run build` → static export succeeds.
6. Manually load `/portal/profile/account` in FR cookie state →
   labels read in French.

# #61 — Patient detail page + Quick Actions navigation (web full slice)

## Task
Surface every encounter for one patient identifier on a single
`/portal/patients/{identifier}` page. Update the B2 Quick Actions
identifier-search modal so a hit on a known identifier jumps to that
patient page (showing all matches at once) instead of jumping straight
to a single session.

This closes the web side of issue #61 (longitudinal patient context).
PR #164 shipped the foundation: KMS-encrypted identifier column,
`GET /me/patients/{identifier}/sessions`, inbox-row identifier chip,
⌘K palette identifier search, B2 Quick Actions identifier search modal.

## Why
The B2 identifier search modal currently funnels a multi-match result
through "pick a session" — but the physician's question when they type
a chart number is "show me everything for this patient", not "pick the
session you want first". The new page is the correct landing surface;
the modal just becomes a launcher for it.

The dedicated page also makes the URL shareable inside the legitimate
consumer (one clinician's session) — a physician can bookmark a
returning patient's encounter rail without re-running search.

## CLAUDE.md gates

### PHI in URL paths
The identifier is in the URL path. This is acceptable per data
classification because:
- `/me/patients/{identifier}/sessions` is owner-scoped on the backend
  (`SessionModel.clinician_id == user.user_id` filter on line 1014 of
  `backend/app/api/v1/me.py`); another clinician hitting the same URL
  gets an empty list.
- The browser title is generic ("Patient encounters") — the identifier
  is not pushed into `document.title` so it does not leak into
  browser-history previews / OS task-switchers.
- No `console.log` of the identifier on the client.
- No Referer leakage to third-party domains — the page never makes a
  cross-origin request whose Referer would carry the path.
- The identifier is URL-encoded when navigating so a `/`-containing
  identifier is safe.

### Descriptive-mode boundary
No LLM calls in this slice. Page renders existing session data only.

### Append-only audit log
No new audit events. The endpoint is read-only.

## Approach

### 1. Extract shared helpers (rule-of-three)
Six files reimplement `humanSpecialty` / `formatRelative` /
`badgeVariantFor`. Extract to `web/lib/session-format.ts` BEFORE
building the new page so the third+ call sites already pass the
DRY gate:

- `humanSpecialty(key)` — identical across all 4 call sites.
- `formatRelative(iso, { withYear?: boolean })` — 5 of 6 call sites
  identical; `notes/page.tsx` is the lone variant that adds `year`
  for older-than-7-day dates. Optional flag preserves both.
- `badgeVariantFor(state)` — only used in dashboard today; will be
  used by the new patient page too. Extracting now lets the patient
  page reuse instead of copy-paste.

All existing call sites switch to the shared module. No behavior
change. Visual smoke test: dashboard renders identically (verified
by tests).

### 2. Build the page
- `web/app/portal/patients/[identifier]/page.tsx` — Server shell with
  `generateStaticParams() => [{ identifier: "_" }]` + `dynamicParams = false`
  for the static-export + Amplify SPA-fallback pattern (same as
  `app/sessions/[id]/page.tsx`).
- `web/app/portal/patients/[identifier]/PatientDetailClient.tsx` —
  Client component. `useParams()` reads the identifier; calls
  `listMySessionsByPatientIdentifier(decoded)`; renders:
  - Back link → `/portal/notes`
  - `PageHeader` (title = formatted identifier, eyebrow = "Patient
    encounters", description with ICU pluralized count + first/last
    visit dates)
  - 3 stat tiles: total sessions / last visit / most-recent specialty
  - Session list — chronological newest-first cards with state badge
    via shared `badgeVariantFor`
  - Loading: PageHeader skeleton + 3 stat skeletons + LoadingSkeleton
    list
  - Empty: reuse `EmptyPanelState` (extracted alongside the helpers
    so the new page imports it instead of re-defining)
  - Failure: red retry banner mirroring the dashboard pattern

### 3. Update Quick Actions
One-line change in `FindByIdentifierDialog.openSession` — instead of
`router.push(/portal/notes/{sessionId})`, route to
`/portal/patients/{encodeURIComponent(identifier)}` and drop the
per-row click handler in favor of either:
  - "Open all" CTA at the top of the result list, or
  - Keep per-row click but make it route to the patient page (same
    destination regardless of which row was clicked).
Chosen: per-row click routes to the patient page. Cleaner UX than
adding a separate CTA, and "which row I clicked" was never the user's
question once the page exists.

### 4. i18n
New `PatientDetail` namespace in `web/messages/{en,fr}.json`. FR at
parity (clinical-neutral phrasing).

### 5. Tests
`web/tests/PatientDetailPage.spec.tsx`:
- Renders PageHeader + stats from a mocked sessions array
- Empty state visible when API returns `[]`
- Sessions sorted newest first
- Clicking a session card navigates to `/portal/notes/{id}`
- Failure path shows retry banner + Retry CTA refetches
- EN + FR catalogs both contain `PatientDetail` namespace + key parity

## DRY / SOLID gates
- **DRY**: 6 → 1 implementations of the format helpers (lift to
  `lib/session-format.ts`); `EmptyPanelState` lifted to
  `components/portal/EmptyPanelState.tsx`.
- **SRP**: Page shell composes; data fetching in a single
  `useEffect`; rendering split into pure subcomponents.
- **Open/Closed**: QuickActions nav change is one line. No new
  routing layer.
- **LSP**: `PatientSessionMatch` shape unchanged across all callers.

## Verification gate
1. `cd web && npm run lint` — clean.
2. `cd web && npm run build` — static export emits
   `out/portal/patients/_/index.html`.
3. `cd web && npx vitest run` — all tests pass including the new
   `PatientDetailPage.spec.tsx`.

## Out of scope
- No new backend changes. Endpoint shipped in PR #164.
- No CommandPalette change. The palette already routes through a
  separate code path; updating it to also land on the patient page is
  a follow-up (low risk because the palette result is one click away
  from the same data via inbox row identifier chip).
- No identifier autocomplete. Single-call lookup is sufficient at
  pilot scale.

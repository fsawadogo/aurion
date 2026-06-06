# Plan — Portal self-audit log page (#162)

## Task
issue #162 — Portal `/portal/audit` self-audit log page so a clinician can
review the audit-trail entries the backend has recorded for their own
sessions (no other clinician's rows, no PHI), with filtering, pagination,
and CSV export of the visible page.

## Why
CLAUDE.md §"Non-Negotiable Technical Rules" pins the audit log as the
load-bearing transparency artifact behind every clinical-safety claim
(masking confirmed, consent confirmed, raw-data purged). Compliance
officers already see the full log at `/audit`; clinicians have no
self-serve surface to audit their own activity. Backlog #162 closes that
gap before the CREOQ/CLLC pilot — a clinician can prove what happened on
their sessions without paging the compliance officer.

Backend support already exists:
- `GET /api/v1/me/audit` — paginated, filterable by date/event_type/
  session_id, scoped to caller's `actor_id` (see
  `backend/app/api/v1/me.py:99-152`). Returns the same
  `PaginatedAuditResponse` shape the admin page consumes.
- Typed client `getMyAuditLog(filters)` already wired in
  `web/lib/portal-api.ts:94-97`. Currently only consumed by the
  dashboard's `ActivityFeed` (most-recent 25, filtered to a tight
  noteworthy allow-list).

## Approach

### Files touched
- **New** `web/app/portal/audit/page.tsx` — server-side shell that reads
  the locale cookie + session and hands off to the client component.
  Mirrors the structure of `web/app/portal/notes/page.tsx`.
- **New** `web/app/portal/audit/MyAuditClient.tsx` — `"use client"`
  component with state for filters, paginated data fetch, and CSV export.
  Reuses the admin `/audit` page's filter-bar + table visual shape
  verbatim where possible (input chrome, badge variants, table layout).
- **New** `web/components/portal/RecentActivityTile.tsx` — small
  dashboard tile that fetches `getMyAuditLog({page_size: 200})` server-
  side once on mount, filters to events ≤ 7 days old, shows the count,
  links to `/portal/audit`. Reuses the dashboard's `StatTile` visual
  pattern so the dashboard grid stays consistent.
- **Modify** `web/components/Sidebar.tsx` — add a "My Activity" entry
  with `Activity` icon under the My Profile section. Visible to
  `CLINICIAN` + `ADMIN` (admin previews per existing convention).
- **Modify** `web/app/portal/dashboard/page.tsx` — slot
  `<RecentActivityTile />` into the headline tiles row. Keep the
  existing four-tile grid; the new tile becomes the fifth column on
  wide screens and wraps on smaller breakpoints. Templates tile stays
  because it's already a teaching surface for the templates feature.
- **Modify** `web/messages/en.json` + `web/messages/fr.json` — new
  `Audit.*` namespace for the page chrome + `MyActivity.*` for the
  tile. Event-type display strings already exist as
  `Dashboard.activity.event.*`; we extract those to a shared
  `AuditEvents.*` namespace and update both the dashboard's
  `ActivityFeed.tsx` and the new audit table to read from
  `AuditEvents.*` so the strings live in exactly one place.
- **New** `web/tests/MyAuditClient.spec.tsx` — mounts with mocked
  `getMyAuditLog`, verifies (1) initial fetch with default page size,
  (2) filter changes trigger refetch with right params, (3) pagination
  click works, (4) CSV download builds the expected blob shape, (5) FR
  renders the right strings.
- **New** `web/tests/SidebarMyActivity.spec.tsx` — verifies the My
  Activity nav entry shows for CLINICIAN and ADMIN roles, and i18n
  parity for `Sidebar.nav.myActivity` between EN + FR.

### Subagent assignments
Single web lane — no backend / iOS / Terraform churn. No subagent
delegation needed.

### Routing
`/portal/audit` is a new static-export-friendly route. No dynamic
segment, so the regular Next `<Link>` works (no need for the
`use-route-segment` plain-anchor workaround). Each row's session_id is
rendered as a `<Link>` to `/portal/notes/[id]` — that destination is a
dynamic segment, so we'll use the plain `<a>` workaround that the rest of
the portal uses (see `app/portal/notes/page.tsx`).

A note may not exist for every audit row (e.g. SESSION_PURGED rows after
data cleanup; consent-only events on a never-recorded session). The
session_id stays clickable regardless — the destination is the note review
screen, which already 404s gracefully when no note exists. We do NOT
need to gate the link visibility.

### Server-side vs client-side
- The page shell stays server-side (mirrors other portal routes) so
  `getTranslations` and cookies work without a `"use client"` boundary
  on the page itself.
- The interactive table is a separate `MyAuditClient.tsx` client
  component (parallels `MyAuditClient` naming in adjacent lanes).

### CSV format
Columns: `timestamp_utc`, `event_type`, `session_id`,
`details_json`. UTF-8 + BOM for Excel-friendly opening. We
intentionally export the JSON-stringified `details` blob rather than
flattening — the audit table is heterogeneous and flattening would
break for events with novel keys. Filename:
`aurion_my_audit_<YYYYMMDD>.csv`.

We mirror the admin /audit page's "export currently-visible page" scope
(NOT full history) so the export is bounded and predictable. A bulk
export of the entire trail is a follow-up.

### Acceptance criteria
- [ ] AC-1: Navigating to `/portal/audit` while signed in as a CLINICIAN
  renders the page chrome (title, filter bar, table) and fires
  `GET /api/v1/me/audit?page=1&page_size=50`. Verified by
  `MyAuditClient.spec.tsx::"loads first page on mount"`.
- [ ] AC-2: Filter bar shows date-from, date-to, event-type select, and
  session-id text input. Changing any filter resets `page` to 1 and
  refetches with the filter as a query param. Verified by
  `MyAuditClient.spec.tsx::"filter change refetches with params"`.
- [ ] AC-3: Pagination buttons render when `total > page_size`. Clicking
  Next/Previous re-fires the fetch with the updated `page`. Verified
  by `MyAuditClient.spec.tsx::"pagination clicks page through"`.
- [ ] AC-4: Each row shows: clinician-local timestamp (rendered via
  `toLocaleString()`), event-type badge (i18n via shared
  `AuditEvents.*` namespace), 8-char-truncated session id as a clickable
  link to `/portal/notes/<full-id>`, and a one-line truncated details
  preview. Verified by `MyAuditClient.spec.tsx::"row shape"`.
- [ ] AC-5: CSV button triggers a download with filename
  `aurion_my_audit_<YYYYMMDD>.csv` and CSV content matching the
  currently-visible rows (verified by intercepting
  `URL.createObjectURL` + asserting the blob contents).
- [ ] AC-6: Sidebar entry "My Activity" with `Activity` icon appears
  between "My Profile" and "AI Prompts" in the rendered nav for
  CLINICIAN. Verified by `SidebarMyActivity.spec.tsx`.
- [ ] AC-7: `RecentActivityTile` on `/portal/dashboard` fetches
  `/me/audit`, filters to events ≤ 7 days old, renders the count, and
  links to `/portal/audit`. Verified manually + by an inline
  documentation test (not a top-priority unit test since it's a
  derived UI surface).
- [ ] AC-8: EN + FR `Audit.*` and `MyActivity.*` namespaces exist and
  contain identical leaf keys. Existing
  `Dashboard.activity.event.*` keys move to shared `AuditEvents.*`
  namespace; both EN and FR catalogs get the namespace; existing
  consumers updated. Verified by `MyAuditClient.spec.tsx::"i18n parity"`.
- [ ] AC-9: All event-type translations used on `/portal/audit` resolve
  via the shared `AuditEvents.*` namespace. The admin `/audit` page
  is NOT touched (admin page is a top-level non-`/portal` route on a
  separate i18n surface — extracting that further is out of scope).

## DRY / SOLID check
- **Existing helpers to reuse**: `getMyAuditLog`, `PaginatedResponse<T>`,
  `AuditEvent`, `AuditFilters` (types), `PageHeader`, `Card`,
  `Badge`, `Button`, `LoadingSkeleton`, `EmptyPanelState`,
  `formatRelative` (timestamps), the existing `Dashboard.activity.event.*`
  i18n keys (which we promote to `AuditEvents.*` rather than duplicate).
- **New helper introduced?** Yes — `RecentActivityTile`. Third copy of
  the "fetch audit events client-side + render a tile" pattern would
  begin if a future lane adds another audit-derived surface; for now
  the tile lives in `web/components/portal/` as a reusable unit rather
  than inlined into the dashboard page. The CSV-builder is a 15-line
  helper that lives next to the only call site (`MyAuditClient.tsx`)
  rather than its own module — only one call site exists; if a second
  lands later we extract.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a (web).
- **SRP**: `MyAuditClient` owns table state; `RecentActivityTile` owns
  tile state. The Sidebar nav array stays a configuration list — no
  filtering logic added.
- **OCP**: new behavior extends the existing `getMyAuditLog` consumer
  set; no new fetch helper, no new audit event type.
- **LSP / DIP**: `getMyAuditLog` returns the same
  `PaginatedResponse<AuditEvent>` shape the admin /audit endpoint
  returns, so both consumers can read the same row type.
- **ISP**: filter object stays `AuditFilters` from `web/types`; we
  don't introduce a new narrower interface.

## Out of scope
- Full-history CSV export (we mirror admin /audit's "export visible
  page only" scope).
- Bulk delete / archive audit rows (audit is append-only — never).
- WebSocket live tail of audit events on `/portal/audit` itself (the
  dashboard's `ActivityFeed` already polls every 30s; the audit page
  is for review, not live monitoring).
- Cross-clinician views (admin `/audit` already covers that).
- Mobile iOS surface for self-audit (iOS already has a session-level
  audit timeline in `SessionDetailView`; a global self-audit screen is
  a follow-up if pilot feedback asks for it).

## Test plan (executable)
1. `cd web && npm test -- --run tests/MyAuditClient.spec.tsx` →
   all assertions pass.
2. `cd web && npm test -- --run tests/SidebarMyActivity.spec.tsx` →
   all assertions pass.
3. `cd web && npm run build` → static export succeeds.
4. Manual smoke (skipped in CI): start the dev server (`npm run dev`),
   sign in as
   `clinician-test@aurionclinical.com / Aurion-Clinician-d1782b52!`
   (per memory `reference_clinician_test_account.md`), navigate to
   `/portal/audit`. Verify the page renders, filter/page changes
   reload data, CSV downloads.

## Security implications
- **PHI**: `/me/audit` returns no PHI (session_id is a UUID, not a
  patient identifier; details blob is non-PHI per `ALLOWED_AUDIT_KWARGS`
  in `app/core/audit_events.py:249-410`). The CSV export reads the
  same blob — no transformation expands the surface.
- **Audit log**: read-only consumer. No write path introduced.
- **Consent gate**: n/a (no recording surface added).
- **Masking proof**: n/a.
- **Secrets**: n/a — uses existing `fetchWithAuth` (Cognito JWT).
- **Descriptive mode**: n/a (no AI prompt touched).
- **Permissions**: `/me/audit` endpoint already gates on
  `get_current_clinician` (CLINICIAN-only role check). Admin role
  hitting `/portal/audit` will 403 from the backend — the page renders
  an empty-state, not a confusing error. We treat this as acceptable
  for an admin "preview" since admins should consult `/audit` for the
  full picture; surfacing "use /audit instead" hint is a polish item.

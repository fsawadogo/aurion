# Plan — Note review: true landscape workspace

## Task
`note-review-landscape` — give the clinician note-review screen (`/portal/notes/[id]`)
a landscape, app-shell layout so the note gets the width and the page stops
being a long vertical scroll. Layout only; PeriTwin brand + note model unchanged.

## Why
CPO (Marie) direction after benchmarking Heidi: "the notes section should be
landscaped like Heidi — it requires a lot of scrolling and real estate is not
given to notes." The earlier TE-4c pass removed the side rail but the screen is
still (a) capped at `max-w-7xl` and centred → big empty margins on wide
monitors, and (b) a single vertical document with five add-on cards stacked
below it → long scroll. This closes both. Web portal is Phase 9; presentation
only — no CLAUDE.md safety surface is touched.

## Approach
One file does the heavy lifting: `web/app/portal/notes/[id]/NoteReviewClient.tsx`.

- **Break the width cap**: drop `aurion-container` (`max-w-7xl`) on this route;
  the workspace fills the width available beside the sidebar.
- **App-shell height (lg+ only)**: root becomes `lg:h-[100dvh] lg:overflow-hidden`
  `flex flex-col`. A slim sticky **header** (breadcrumb + specialty + Stage·v·Provider,
  and the action toolbar) and a **banner strip** are `shrink-0`; the body is
  `flex-1 min-h-0`. Below `lg` it falls back to natural document flow (no fixed
  height) so mobile/tablet stay usable.
- **Two-pane body**: main **note pane** (`flex-1`, own `overflow-y-auto`) +
  a right **extras rail** (`lg:w-[360px]`, own scroll) holding the post-approval
  cards (Orders / PatientSummary / Coding / EMR / PreviewVsFinal). Those cards
  already `return null` until `is_approved`, so the rail is rendered only when
  approved — during review the note takes the full width.
- **Dock the assist chat**: `NoteAssistChat` (already "a Heidi-style grounded
  editor") moves to a `shrink-0` strip pinned at the bottom of the note pane,
  i.e. Heidi's "Ask anything" position. Still gated on `note_review_chat_enabled`.
- **Toolbar moves into the slim header**; the note document loses its outer
  `Card` so it sits directly in the padded scroll area (more note width).

No new components, no new user-facing strings (every `NoteReview.*` i18n key is
reused as-is → EN/FR stay in sync). All handlers, state, and the
`noteBusy`/regenerate/conflict/discard/sign-off logic are relocated verbatim,
not rewritten.

## Acceptance criteria
- [ ] AC-1: On a ≥1280px viewport the note body is wider than the current
      `max-w-7xl` column (no centred cap) — verified visually + by absence of
      `aurion-container` on the page root.
- [ ] AC-2: During review (unapproved note) the page does not scroll as a whole
      on lg+; the note pane scrolls internally while the header/toolbar stay
      pinned — verified visually.
- [ ] AC-3: The five add-on cards render in the right rail only after approval;
      pre-approval the note occupies full width — verified visually.
- [ ] AC-4: All existing behaviour intact — template change regenerates, EN/FR
      switch + loss-gate confirm, Copy (unapproved), assist-chat gate + re-fetch.
      Verified by the existing `web/tests/NoteReviewPage.spec.tsx` staying green.
- [ ] AC-5: Collapses to a single readable column below `lg` — verified visually
      at 375px + 768px.

## DRY / SOLID check
- **Existing helpers reused**: `PageHeader` pattern replaced inline (this page
  only); `NoteAssistChat`, `CompletenessRing`, `NoteSectionCard`, `SignOffControl`,
  `ConflictsBanner`, `DiscardPrompt`, `buildNoteText` all reused unchanged;
  Tailwind design tokens (`hairline`, `navy-*`, `bg-canvas`, `rounded-aurion-*`)
  reused — no new global CSS class.
- **New helper introduced?**: No. Layout is expressed with existing utilities;
  render tree is reorganised, not abstracted.
- **iOS UI task?**: N/A (web).

## Out of scope
- Persistent session-list column beside the note (Heidi's 2nd pane) — deferred.
- Heidi's Context/Transcript/SOAP tabs — reviving transcript/citations reverses
  a prior product decision; explicitly not in this PR.
- Any colour / brand change (stays navy/gold).
- The `/portal/notes` list page and any backend/iOS change.

## Test plan (executable)
1. `cd web && npm run test -- NoteReviewPage` → all green (behaviour contract).
2. `cd web && npm run test` → full web unit suite green (no cross-file regressions).
3. `cd web && npx tsc --noEmit` (or the project's typecheck) → no type errors.
4. `cd web && npm run lint` → clean.
5. Visual: `npm run dev`, open a note at ≥1280px (full-width, internal scroll),
   an approved note (right rail present), and 375/768px (single column).

## Security implications
None. Presentation-only change to one client component. No PHI handling, no AI
prompt, no audit-log path, no consent gate, no secrets. Copy-to-clipboard and
export behaviour are relocated unchanged (still `noteBusy`-gated).

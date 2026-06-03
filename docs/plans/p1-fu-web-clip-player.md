# P1-FU-WEB-CLIPS — Web portal clip player + chip indicator

**Canonical plan:** [`/Users/fsawadogo/.claude/plans/dual-mode-visual-evidence.md`](../../../../.claude/plans/dual-mode-visual-evidence.md)
(Phase 1, web follow-up to backend P1-6-FU + iOS P1-6.)

**Type:** web-only follow-up. No backend or iOS changes. The backend
(P1-6-FU PR #207) already populates `evidence_kind`, `duration_ms`, and
`clip_url` on every visual `CitationExpansion`. The iOS reviewer
(`CitationChip` + `FullClipView` from P1-6) already renders the
play-triangle indicator and a native modal player. The web portal's
`ClaimChip` and `NoteSectionCard` ignore the new fields — compliance
officers, eval team, and admins reviewing notes through the web see
clips as plain "V" chips that take them to the transcript pane (the
existing frame-chip behaviour) instead of letting them play the actual
encoded window.

## Why

Eval team and compliance officers do their note review through the web
portal, not iOS. P1-6's clip evidence is the central artifact of Phase
1 — without a way to actually play it on the web, the cohort that
reviews the most notes by volume can't audit the evidence layer. This
PR brings the web reviewer to feature parity with the iOS reviewer for
clip-kind citations.

## Scope

1. **`web/types/index.ts`** — extend `CitationExpansion` with three
   additive optional fields mirroring `backend/app/api/v1/notes.py`:
   `evidence_kind?: "frame" | "clip" | null`,
   `duration_ms?: number | null`,
   `clip_url?: string | null`. All three optional so existing decoders
   without these fields still parse (open/closed; additive contract).

2. **`web/components/portal/ClaimChip.tsx`** — when the chip's citation
   has `evidence_kind === "clip"` AND `source_type === "visual"`, render
   a small `Play` (lucide-react, size 10px, navy-on-gold-circle) overlay
   at the trailing-bottom of the "V" badge. Visual parity with iOS
   `CitationChip.swift` (the `play.triangle.fill` overlay). Clip chips
   also flip the V badge fill to `bg-gold-500` to mark "richer
   evidence" — same rule as iOS `badgeFill`.

   Click on a clip chip opens `FullClipModal` instead of (in addition
   to) the existing source-jump callback. Frame chips keep their
   existing transcript-jump behaviour unchanged (open/closed: the
   `evidence_kind="frame"` path is the existing path).

3. **`web/components/portal/FullClipModal.tsx`** (new component) — modal
   with:
   - HTML5 `<video controls autoplay loop>` element rendering the
     `clip_url`. Autoplay is muted by default (browser autoplay policy)
     and the controls let the reviewer un-mute.
   - Dark backdrop (`bg-black/85`), photo-viewer aesthetic matching the
     iOS `FullClipView`. Full-screen on mobile, `max-w-3xl` on desktop,
     centred.
   - Header with M:SS timestamp (derived from `frame_timestamp_ms`) and
     a duration pill ("7.0s") derived from `duration_ms`.
   - Close button (top-right) and a dismissable backdrop + `Escape` key
     handler — three close affordances mirror modal best practice.
   - Empty state: if `clip_url` is null/empty, show the localized
     `ClipModal.unavailable` message and a Retry hint instead of an
     empty `<video>` element.

4. **i18n EN+FR catalogs** — add `ClipModal` namespace with five keys:
   `title`, `duration`, `close`, `unavailable`, `controls`. French at
   parity (per memory `feedback_premium_ui_design_system`).

5. **Tests** `web/tests/CitationChip.spec.tsx` + `FullClipModal.spec.tsx`
   — Vitest + React Testing Library + jsdom. Cover:
   - Chip with `evidence_kind="clip"` renders the Play icon.
   - Chip with `evidence_kind="frame"` (or unset) doesn't render Play.
   - Click on a clip chip invokes the modal-open callback.
   - `FullClipModal` with a `clip_url` renders a `<video>` with the
     correct `src`.
   - `FullClipModal` with `clip_url=null` renders the unavailable copy
     (EN and FR catalogs both checked).
   - Escape key closes the modal.
   - Backdrop click closes the modal.
   - Inner content click does NOT close the modal.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - `ClaimChip` already owns the per-source-type badge rendering — extend it,
    don't fork it.
  - `useTranslations("ClipModal")` follows the existing next-intl pattern
    (`NotificationBell`, `CommandPalette`, `LocaleSwitcher`).
  - Tailwind tokens: `bg-aurion-card`, `text-aurion-primary`,
    `border-aurion-hairline` already adapt to dark mode — no new colour
    tokens.
- **New helper introduced?**: yes — `FullClipModal` as a sibling to
  `ClaimChip`. Justified by SRP (chip = badge + click; modal = video
  presentation). One-helper rule respected: there's exactly one play
  modal in the portal.
- **SRP**: `ClaimChip` keeps its single responsibility (badge + onClick
  fan-out). `FullClipModal` owns one thing: the video viewer surface.
- **OCP**: clip-kind branch is additive — frame chip path is byte-for-byte
  the same diff. No `if (provider == ...)` branching introduced.
- **LSP**: `CitationExpansion` decoder shape stays identical for
  non-visual claims; new fields are optional + nullable + default
  undefined.

## Out of scope

- Frame stills viewer. The web portal currently shows V-chip
  transcripts only on click — no frame-still modal exists today. Not
  shipping one here.
- Backend changes. Already shipped in PR #207.
- iOS changes. Already shipped in PR #204.
- Audit events for clip URL fetches. Per backend doc — too noisy.
- Caching/preloading the clip video. The browser handles range requests
  on the signed URL.

## Acceptance criteria

- [ ] AC-1: A clip-kind visual citation rendered through `ClaimChip` shows
      a Play icon overlay on the V badge. Verified by Vitest snapshot.
- [ ] AC-2: A frame-kind visual citation through `ClaimChip` does NOT
      render the Play icon. Verified by Vitest.
- [ ] AC-3: Clicking a clip-kind chip invokes the modal-open handler.
      Verified by Vitest user-event.
- [ ] AC-4: `FullClipModal` with `clip_url="https://x/clip.mp4"` renders
      `<video src="https://x/clip.mp4">`. Verified by Vitest.
- [ ] AC-5: `FullClipModal` with `clip_url=null` renders the localized
      unavailable message. Verified by Vitest (EN + FR catalogs).
- [ ] AC-6: Escape key closes the modal. Verified by Vitest user-event.
- [ ] AC-7: Backdrop click closes the modal; click inside the video
      container does NOT close. Verified by Vitest.
- [ ] AC-8: Both `messages/en.json` and `messages/fr.json` contain all
      five `ClipModal.*` keys. Verified by Vitest catalog parity check.
- [ ] AC-9: `npm run lint` is clean.
- [ ] AC-10: `npm run build` succeeds (no TypeScript errors).

## Test plan

```bash
cd web && npm run lint
cd web && npm run build
cd web && npm test -- --run
```

## Security implications

- **No PHI in rendered URLs**: `clip_url` is a short-TTL (1 h) signed S3
  URL; the URL itself contains no PHI but the rendered HTML attribute is
  visible in the DOM only to the authenticated reviewer who fetched it.
- **No console.log of `clip_url`**: don't log the signed URL anywhere; if
  the video fails to play, surface the localized unavailable message and
  let the network panel diagnose.
- **Descriptive-mode**: no AI prompt changes. Pure UI work.
- **Consent gate intact**: this surface only renders for sessions that
  already passed consent + completed Stage 2 (the note exists).

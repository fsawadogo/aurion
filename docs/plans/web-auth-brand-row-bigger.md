# Portal: bigger brand row on the auth screens

**Branch:** `lane-web/auth-brand-row-bigger` · **Lane:** web (portal)

## Why

Pilot feedback from Dr. M Gdalevitch (relayed by Uzziel, 2026-08-03,
screenshots of both the desktop dark and mobile light sign-in): "but for
portal its super small even on web" — the PeriTwin brand row above the
Sign-in card reads tiny at every size.

## Current state

`web/components/auth/AuthScreenShell.tsx:51-68` — shared chrome for
login/forgot/reset: mark at `h-10` (40px) + live-type wordmark at
`text-[24px]`, `gap-2.5`. Part of Faïçal's 2026-07-25 centered-column
redesign ("compact brand row" per its comment) — the structure stays,
only the brand scale changes.

## Change

One component, both themes, all three auth screens at once:

- Mark: `h-10` → `h-16 sm:h-20` (40 → 64/80px).
- Wordmark: `text-[24px]` → `text-[36px] sm:text-[44px]`.
- `gap-2.5` → `gap-3`; docstring updated (compact → prominent, names the
  pilot feedback).

## Acceptance criteria

- AC-1: /login brand row measures ≥64px mark + ≥36px wordmark on mobile,
  ≥80px + ≥44px at sm+, verified live; wordmark two-tone hexes untouched
  (dark-mode "Twin" stays visible per the existing comment).
- AC-2: forgot-password and reset-password inherit (shared shell — no
  per-screen edits).
- AC-3: web gates green: vitest, lint, build.

## Out of scope

- Marketing site (desktop is "good" per Marie; mobile restructure is its
  own branch `lane-website/mobile-header-restructure`).
- iOS app logo — Faïçal handoff item.
- Portal in-app topbar/sidebar branding — feedback was the sign-in page.

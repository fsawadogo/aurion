# Website: header logo → the footer's full lockup

**Branch:** `lane-website/header-logo-full-lockup` · **Lane:** website (marketing site; builds on #713's trimmed header, now on main)

## Why

Uzziel (2026-08-01): "For the web experience can u make the logo at the top of
the page be like the one at the bottom?" — the header should carry the same
brand artwork as the footer.

## Current state

- Header (`landing-header.tsx:35`): `/peritwin-nav.png` — 901×250 horizontal
  strip, icon + wordmark, tagline deliberately omitted (the code comment says
  "tagline omitted so it stays legible at nav height").
- Footer (`landing-footer.tsx:33`): `/peritwin-logo.png` — 1248×667 full
  lockup; the purple tagline "Your clinical digital twin. Ask Peri." is part
  of the artwork. Also used as the OG/social image (`layout.tsx:38`).
- `peritwin-nav.png` has exactly one consumer (the header). `peritwin-mark.png`
  has zero consumers already (pre-existing orphan).

## Change

1. `landing-header.tsx` — swap the header `Image` to `/peritwin-logo.png`
   with its real intrinsic size (1248×667); update the comment (full lockup
   per CPO request, replacing the tagline-omitted rationale); set the img
   `alt` to brand — tagline (mirroring the footer's alt). Because the new
   art is much taller per unit width (1.87:1 vs 3.6:1), bump the rendered
   heights one notch — `h-12 md:h-16 lg:h-20` (was `h-11 md:h-14 lg:h-16`)
   — so the lockup keeps presence in the fixed glass header without
   ballooning it.
2. Delete `public/peritwin-nav.png` — orphaned by the swap; git history
   keeps it if the decision reverses.

## Explicitly out of scope

- Footer, OG metadata (`layout.tsx`) — already use the full lockup.
- `peritwin-mark.png` (pre-existing zero-consumer asset) — /simplify may
  flag it; decide there, not here.
- The parked redesign branch.

## Acceptance criteria

- AC-1: Header renders `/peritwin-logo.png` at all breakpoints (desktop +
  mobile), wrapped in the same home link with unchanged link aria-label.
- AC-2: No reference to `peritwin-nav.png` remains in `website/`; the file
  itself is gone from `public/` and from the fresh export.
- AC-3: Footer + OG image untouched (`peritwin-logo.png` still referenced
  by both).
- AC-4: Visual check — screenshot of the rendered header at desktop and
  mobile widths attached to the receipt/PR conversation.

## Gates (website lane)

- `tsc --noEmit` clean (build has ignoreBuildErrors — run explicitly).
- `pnpm build` static export green, 17/17 pages.
- Exported-HTML assertion: header markup references `peritwin-logo.png`;
  zero `peritwin-nav.png` occurrences anywhere in `out/`.
- Dev-server screenshots (desktop + mobile) for the visual AC.

Then verify-receipt → /simplify (4 agents) → PR. Uzziel merges; site.yml
auto-deploys peritwin.com (peritwin.ai follows once Faïçal's #715 DNS
cutover lands).

# Website: header and footer logos at the same size (260px)

**Branch:** `lane-website/logo-size-parity` · **Lane:** website · Follows #721

## Why

Uzziel (2026-08-02): the two logos should be exactly the same size, and the
size is the footer's — confirmed via question: "Both at ~260px (bottom's
size)", accepting the taller header bar (~190px desktop).

## Current state (post-#721)

- Header: `LOGO` at `h-12 md:h-16 lg:h-20` → renders ~90/120/150px wide.
- Footer: `h-auto w-full max-w-[260px]` → renders 260×139 at every
  realistic width.
- Recorded watch items from #721 now TRIGGER: `md:pt-32` (128px) on the four
  pages and `scroll-padding-top: 6rem` were sized for a ≤130px header; a
  260px-wide logo makes the md+ header ~188px tall.

## Change

1. `landing-header.tsx` — logo `w-44 md:w-[260px] max-w-full h-auto`:
   exact 260px parity with the footer from md up; `w-44` (176px) on phones
   where 260px cannot share the bar with the toggle + language switcher
   (measured budget ~179px). Mobile keeps maximum size that fits.
2. `landing-footer.tsx` — same sizing expression (`w-[260px] max-w-full
   h-auto`) so parity is structural, not coincidental (rendered size
   unchanged: it was already 260).
3. **Layout repairs, measurement-driven**: live-measure home, contact,
   partners, pilots at 375/900/1440; wherever first content underlaps the
   taller fixed header, bump the page-top padding (`md:pt-32` → what the
   measurements demand) and raise `globals.css` `scroll-padding-top` so the
   anchor path clears the ~188px md+ header with real margin (additive
   scroll-mt-24 gives 192px today — 4px is too thin).

## Out of scope

- `/prototype` header overlap (pre-existing, chip filed in #721 review).
- The deferred logo-sm.webp payload chip (unchanged by sizing).

## Acceptance criteria

- AC-1: Header and footer logo rendered widths are EQUAL at md+ (260px),
  measured live; mobile header logo is the max that fits its row.
- AC-2: No page's first content underlaps the fixed header at 375/900/1440,
  measured live on all four pages.
- AC-3: Footer anchor jumps land targets clear of the taller header.
- AC-4: tsc clean; export 17/17; screenshots/measurements recorded.

## Gates

tsc --noEmit → build → exported-HTML checks → live DOM measurements →
receipt → /simplify → PR (§9). Uzziel merges; site.yml auto-deploys.

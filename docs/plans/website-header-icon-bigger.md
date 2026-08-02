# Website: bigger header icon, writing untouched (composite lockup)

**Branch:** `lane-website/header-icon-bigger` · **Lane:** website · Follows #724/#727

## Why

Uzziel (2026-08-02): "anyway to make the icon (the two faces) bigger but
leave the writting as is?" — approved live prototype, then "ok merge".
Confirmed via question AFTER discovering #727: ship the composite over
Faïçal's tagline restoration (his #727 re-added the tagline for footer
consistency ~2h after Uzziel's #724 removal merged — likely unaware; the
question surfaced the collision and Uzziel chose the composite; a heads-up
message for Faïçal accompanies the PR).

## Change

1. Header renders the lockup as TWO pieces so they scale independently:
   - `public/peritwin-icon.png` (NEW, 331×524) — the two-faces mark,
     tight-cropped from `peritwin-mark.png`'s 600×600 frame (the frame
     padding ate the first attempt's growth); rendered `h-14 md:h-28`
     (56px / 112px — the faces gain ~27% mobile, ~56% desktop).
   - `public/peritwin-word.png` (NEW, 705×250) — the "PeriTwin" wordmark,
     pixel-cropped from `peritwin-nav.png` (gap-detected split at x≈200);
     rendered `ml-1 h-[44px] md:ml-3 md:h-[72px]` — exactly today's text
     size at both breakpoints. No tagline (per #724's standing direction).
2. `lib/site.ts` — remove `NAV_LOGO` (no consumer after the composite) and
   `LOGO_WIDTH_CLASS` (single consumer left → inlined back in the footer;
   this reverses the previous round's extraction — the altitude agent's
   dissent proved right once the artworks stopped sharing a width story).
   `LOGO` stays (footer + OG share it).
3. Delete `public/peritwin-nav.png` (orphan again once the wordmark crop
   replaces it; git history keeps it — second deletion of this file).
4. Footer, OG, favicons (#727's good half): untouched.

## Acceptance criteria

- AC-1: Desktop faces ≥100px tall, wordmark exactly 203×72 (unchanged);
  mobile faces 56px, wordmark 124×44 (unchanged); measured live.
- AC-2: Mobile row fits at 375 (no overflow; link ≤165px) and tap target
  ≥44px (min-h-11 retained).
- AC-3: Zero references to peritwin-nav.png / NAV_LOGO / LOGO_WIDTH_CLASS
  after the change; footer + og:image still on peritwin-logo.png.
- AC-4: tsc clean; export 17/17; exported HTML shows both pieces preloaded.

## Gates

tsc → build → export assertions → live measurements → /simplify (3
agents) → receipt → PR → independent review → merge (pre-authorized:
"ok merge" + confirmed post-#727) → watch site.yml → verify live.

# Website: mobile header restructure — logo fills the row, EN/FR moves under

**Branch:** `lane-website/mobile-header-restructure` · Follows #729 · Pilot feedback

## Why

Dr. M Gdalevitch (via Uzziel, 2026-08-03): "its pretty small both on the
portal page and the home page. can the the eng/french be under and the
logo take up the whole space next to the menu i think on mobile."
Desktop marketing site explicitly good per Marie — mobile only.

## Change

1. `landing-header.tsx` — below `md` the header becomes TWO rows:
   - Row 1: logo (scaled UP into the space the switcher vacates: icon
     `h-12 min-[360px]:h-18 md:h-28`, word `h-10 min-[360px]:h-14
     md:h-18`) + hamburger. The switcher wrapper is `hidden md:block`
     in row 1 (unchanged position from md up).
   - Row 2 (`md:hidden`): slim right-aligned EN/FR bar under row 1.
   - md/lg+: unchanged layout (row 2 absent, switcher in-row).
2. `language-switcher.tsx` — revert #729's sub-360 pill compaction (now
   moot: on their own row the 44px pills fit any width) back to the
   simple 44px-touch / 36px-lg pair.
3. Page top paddings retuned to the new sub-md header (~157px vs 90):
   contact/partners/pilots `pt-28 md:pt-48` → `pt-48`; home `pt-24` →
   `pt-36` (md side unchanged). Exact values confirmed by live
   measurement, same gate as #728/#729.

## Numbers (pre-computed, to be live-verified)

- 375: logo pieces 45+158=207px of a 259px budget (was 163/165 with the
  switcher in-row) — the "whole space" ask; faces 72px (+29% vs today).
- 320: 147px of 204 budget. md band: row 1 only, 162px header as today.
- Header heights MEASURED: 144px (<360), 168px (360-767), 162px (md+,
  unchanged). Anchor jumps land the section top at exactly 192px
  (scroll-padding 6rem + scroll-mt-24, additive — re-measured by forced
  instant scrollIntoView this round, consistent with #728/#729's
  empirical landings) → +24px clear of the 168px header, heading +72.
  Thin but positive; watch item if the sub-md header ever grows again.

## AC

- AC-1: below md — no switcher in row 1, EN/FR on its own row, logo
  measurably bigger (faces ≥72px at 375); md+ byte-identical geometry.
- AC-2: no page content under the header at 320/375/640/768/1024/1440,
  measured; no row overflow anywhere.
- AC-3: tsc clean; export 17/17; drawer/aria unchanged.

## Gates

tsc → build → live measurements (6 widths × 4 pages) → pt tuning →
/simplify (1 agent) → receipt → PR → review. Uzziel merges.

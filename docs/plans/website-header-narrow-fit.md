# Website: header fits 320-class phones (wordmark stopped overlapping EN/FR)

**Branch:** `lane-website/header-narrow-fit` · Follows #728

## Why

Uzziel (2026-08-02, device screenshot): "the name on mobile overlaps eng
french (buttons can be smaller)". Screenshot decodes to a 320pt viewport
(960×2079 @3x — iPhone Display Zoom): the exact sub-360 regime #728's
review documented. Reproduced at 320 emulated: wordmark overlapped the
switcher by 15px.

## Change (both gated to `min-[360px]` so ≥360 is byte-identical)

1. `language-switcher.tsx` — pills compact to 36px below 360
   (`min-h-9 min-w-9`, restoring 44px at `min-[360px]:` and keeping the
   lg 36px look), per the CPO's "buttons can be smaller". Comment updated
   with the trade-off.
2. `landing-header.tsx` — logo pieces one notch down below 360: icon
   `h-11` (44px), wordmark `h-8` (32px).

## Measured (live DOM)

- 320: pieces 28×44 + 90×32, switcher 86px, **+26px gap** (was −15
  overlap), no row overflow.
- 360: 35×56 + 124×44, switcher 102, 9px gap — identical to pre-change.
- 375: identical to pre-change (24px gap).

## AC

- AC-1: no overlap at 320; AC-2: 360/375/md+ byte-identical; AC-3: tsc
  clean, export 17/17, min-[360px] variants present in emitted CSS.

## Gates

tsc → build → CSS-emission assertion → /simplify (1 agent, tiny diff) →
receipt → PR → independent review → report. Uzziel merges.

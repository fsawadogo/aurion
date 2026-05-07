# Aurion Brand — Design System for Video

Source of truth: `aurion-design-system/project/colors_and_type.css`. These values are mirrored from the Aurion iOS Theme.swift and components.jsx — do **not** invent new colors or substitutions.

## Palette

### Brand
- `--navy-500` `#0D1B3E` — brand primary, primary text on light, hero backgrounds
- `--gold-400` `#C9A84C` — brand accent, CTAs, record-pulse, gold halos
- `--gold-300` `#D7BB5F` — gold gradient stop
- `--navy-600` `#0A1530` — deeper navy for vertical gradients

### Surfaces (light mode — default)
- `--bg-canvas` `#F8F9FA`
- `--bg-surface` `#FFFFFF`
- `--bg-surface-alt` `#EEF0F3`

### Foreground
- `--fg-1` `#0D1B3E` (navy)
- `--fg-2` `#4A5160`
- `--fg-3` `#6B7280`

### Status
- `--status-done-fg` `#2E9E6A` / `--status-done-bg` `#E6F5EE`
- `--status-pending-fg` `#8E7330` / `--status-pending-bg` `#FBF6E6`
- `--status-recording-fg` `#D9352B` / `--status-recording-bg` `#FBE7E5`
- `--status-conflict-fg` `#D9941F` / `--status-conflict-bg` `#FBF1DC`

### Note section accents (left bars)
- `--section-info` `#2D6CDF`
- `--section-exam` `#2E9E6A`
- `--section-assessment` `#D9941F`
- `--section-plan` `#0D1B3E`

## Typography

System SF stack — no custom fonts required.

```css
--font-display: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", system-ui, sans-serif;
--font-text:    -apple-system, BlinkMacSystemFont, "SF Pro Text",    "Inter", system-ui, sans-serif;
--font-mono:    ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
```

### Type scale (video-appropriate, scaled up from iOS pt)
- Hero title: 96–128px, weight 700, tracking -0.02em
- Section title: 64–80px, weight 600, tracking -0.01em
- Subhead: 36–44px, weight 500
- Body / caption: 28–32px, weight 400
- Caps label: 22px, weight 600, tracking 0.08em, uppercase
- Numeric (timer, %): tabular-nums, ui-monospace

## Corners
- Buttons: 12px
- Cards: 16px
- Sheets / hero panels: 20–28px
- Pills / chips: fully rounded (`9999px`)

## Density
- Iphone screen padding: 20px
- Card inner padding: 16–24px
- Stack gap: 12–24px

## Depth
**Subtle.** Layered drop shadows only on cards and elevated chrome — no neumorphism, no inner shadows, no gloss.

```css
--sh-2: 0 1px 2px rgba(13, 27, 62, 0.04), 0 4px 16px rgba(13, 27, 62, 0.06);
--sh-3: 0 2px 4px rgba(13, 27, 62, 0.06), 0 12px 32px rgba(13, 27, 62, 0.10);
--sh-record-pulse: 0 0 0 8px rgba(201, 168, 76, 0.18), 0 12px 32px rgba(201, 168, 76, 0.36);
```

## Motion

**Calm and declarative.** This is a clinical product — no bounces, no spring overshoots, no wiggle, no playful keyframes.

- Primary easing: `cubic-bezier(0.32, 0.72, 0, 1)` — iOS easing. Map to GSAP as a `CustomEase` or use `power3.out` / `power2.out` as the closest stock substitute.
- Durations: `120ms` (micro), `200ms` (short), `320ms` (medium), `500ms` (long)
- Entrance pattern: opacity + small y-offset (12–24px). Not scale-from-zero.
- The breathing halo on the record button uses a 1.6–2.4s sine cycle.
- Audio-reactive bars are deterministic envelopes, not random.

## What NOT to Do
- No spring overshoot, no bounce, no elastic easing
- No scale-up-past-1 punches
- No emoji in titles
- No drop-cap/serif typography — system sans only
- No bright primary colors outside navy/gold/status set
- No gradient text on body content (gradient permitted on hero `Aurion` mark)
- No animated gradients on dark backgrounds (H.264 banding) — use radial or solid + localized glow
- No abstract clinical claims in narration — descriptive only, never diagnostic

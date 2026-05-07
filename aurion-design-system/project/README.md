# Aurion Design System

> **Aurion Clinical AI** — a wearable AI physician assistant that records clinical encounters and generates structured medical notes. The iOS app is the physician's primary surface during patient visits.

This design system captures the visual, content, and component foundations for the Aurion iOS app (iPhone + iPad universal). It is the canonical reference for any new screen, marketing asset, or prototype.

---

## Sources

This system was created from a written design brief only. **No codebase, Figma file, or screenshots were attached** to the project. All interpretations below are extrapolated from the brief and Apple Human Interface Guidelines for iOS.

If you have reference material — existing screens, a Figma file, brand assets, the iOS codebase — please attach it via the **Import** menu so the system can be tightened to match real production.

---

## Product context

**Aurion** sits at the intersection of clinical software and a luxury hardware product. The physician wears Ray-Ban Meta smart glasses; the iOS app is the cockpit they touch between rooms. The tone is "luxury medical device" — calm, confident, and minimal — explicitly **not** "hospital software."

- **Users:** 3–5 physicians at a plastic / orthopedic surgery clinic
- **Surface:** iOS universal (iPhone + iPad), with split-view layouts on iPad
- **Core loop:** Start session → record → review → approve & sign
- **Constraint:** ≤2–3 taps to start recording from the dashboard. One-handed, glanceable, premium.

## Products in this system

- **iOS app** (primary, this brief) — universal iPhone + iPad
- *(Marketing site, admin dashboard, etc. — not in scope of the current brief)*

---

## Index — what's in this folder

| File / folder | Purpose |
|---|---|
| `README.md` | This file. Brand & system overview. |
| `SKILL.md` | Cross-compatible skill manifest for Claude Code. |
| `colors_and_type.css` | Design tokens: color, type, spacing, radii, shadow. |
| `fonts/` | Webfonts (SF Pro substitutes — see Type section). |
| `assets/` | Logos, icons, illustrations, imagery. |
| `preview/` | Design System tab cards (one HTML file per card). |
| `ui_kits/ios/` | iOS UI kit — components + click-thru screens. |

---

## Content fundamentals

Aurion's voice is the voice of **a quiet, expert colleague.** Sentences are short. Words are deliberate. Nothing is cute.

### Tone

- **Calm and declarative.** State what is, not what could be. *"Note ready."* not *"Your note is ready! ✨"*
- **Confident, never chirpy.** No exclamation points outside of one-word success states. No emoji in product UI.
- **Clinical-adjacent, not clinical.** We use the physician's vocabulary (*encounter*, *visit*, *note*, *template*, *consent*) but never feel like an EHR.
- **Quiet authority.** Avoid hedging language — *"may"*, *"might want to"*, *"perhaps"*. Be direct.

### Casing

- **Title Case** for nav, primary buttons, and section headings: `Generate Note`, `Quick Start`, `Recent Sessions`.
- **Sentence case** for descriptive body copy and form labels: *"What brings the patient in today?"*
- **ALL CAPS** reserved for status badges and the `REC` indicator only. Tracked +0.08em.

### Person & address

- **"Dr. Lastname"** in greetings — never first names, never just "you."
- **Imperative second person** for actions: *"Approve & Sign"*, *"Confirm patient consent."*
- **First person plural is rare.** Aurion is not "we" — it's the tool. *"Note ready"* not *"We've prepared your note."*

### Specific examples

| Context | ✅ Aurion | ❌ Not Aurion |
|---|---|---|
| Greeting | `Good morning, Dr. Chen` | `Hey Sarah! 👋` |
| Empty state | `No pending reviews` | `Looks like you're all caught up! 🎉` |
| Recording | `REC · 02:47` | `Recording in progress…` |
| Consent gate | `Confirm patient consent` | `Please confirm that the patient has consented` |
| Success | `Note ready` | `Your note has been successfully generated!` |
| Error | `Recording paused. Tap to resume.` | `Oops! Something went wrong.` |
| CTA | `Start Session` · `Approve & Sign` | `Get started` · `Submit` |
| Footer | `For authorized personnel only.` | `© 2026 Aurion Inc.` |

### Numbers, time, units

- **Timer:** `MM:SS` (zero-padded). Sessions over an hour: `H:MM:SS`.
- **Dates:** `Apr 27` for recent, `Apr 27, 2026` for older. Never `04/27/2026`.
- **Counts:** spelled out under ten in prose (`three sessions today`); numerals in UI chrome (`3 pending`).

### What we never do

- No emoji in product UI. (Country flags on the language picker are the only iconographic exception.)
- No marketing-speak: *"AI-powered"*, *"revolutionary"*, *"seamless"*, *"effortless"*.
- No exclamation points except one-word states.
- No second-person possessives in chrome: *"Dashboard"*, not *"Your Dashboard."*

---

## Visual foundations

### Color

The palette is **two colors and a stack of grays.**

- **Navy `#0D1B3E`** is the brand. It carries the recording surface, headers on dark mode, and the logo mark.
- **Gold `#C9A84C`** is the only accent. It earns attention — primary CTAs, the record button, the progress bar, the avatar gradient. Never decorative.
- **Light gray `#F8F9FA`** is the canvas in light mode.
- **White cards** with a soft, low shadow do the layout heavy lifting.

Status uses a tight semantic set: **green** = done, **gold** = pending, **red** = recording, **gray** = archived. Conflicts in note review use **amber** (warmer than gold) so they read distinctly.

Dark mode swaps the canvas to a deep navy (`#0A1530`) and lifts cards to `#152348`. Gold and white are the only chromatic anchors.

### Type

**SF Pro** (system) is the only typeface — Display for headings ≥20pt, Text for everything else, Mono for the recording timer. Inter ships as the web substitute (see Type Substitution below).

- Tight tracking on display sizes (`-0.02em` at 34pt+).
- Generous line-height on body (1.45–1.5).
- Numerals are tabular when they're in motion (timer, counts) so they don't jitter.

### Spacing & rhythm

A **4pt base grid.** Tokens: `2 / 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 56 / 80`. Most card padding is `20`; section gaps are `32`; screen edge insets are `20` on iPhone, `32` on iPad.

### Backgrounds

- **Solid surfaces** are the default. No gradients on cards.
- **The login screen and capture screen are the only places gradients appear** — a soft navy radial gradient that fades from `#0D1B3E` at the bottom to `#1A2E5C` at the top.
- **No patterns, no textures, no hand-drawn illustrations.** This is a medical device; ornamentation undercuts trust.
- **No imagery in chrome.** The only imagery is the user avatar (initials on a gold gradient).

### Borders, shadows, elevation

- Cards: `1px` hairline border `rgba(13, 27, 62, 0.06)` + soft shadow `0 1px 2px rgba(13, 27, 62, 0.04), 0 4px 16px rgba(13, 27, 62, 0.06)`.
- Pressed cards: shadow collapses to `0 1px 2px` only.
- Modals/sheets: `0 -8px 32px rgba(13, 27, 62, 0.12)` (top-shadow for bottom sheets).
- **No inner shadows.** No glass blur on chrome (the iOS system blur on tab bars is fine; we don't add our own).

### Corner radii

- **Buttons:** `12pt`
- **Cards:** `16pt`
- **Sheets / modals:** `20pt` top-only
- **Avatars / circular badges:** full
- **Pills (status badges, filter chips):** full
- **Record button:** full circle, `78pt` diameter

### Hover, press, focus

iOS doesn't hover, but iPad with pointer does. We treat all three uniformly.

- **Hover (iPad pointer):** background lifts by 4% white overlay; cursor becomes pointer.
- **Press:** `scale(0.97)` + shadow collapse, `120ms` ease-out. Haptic on key actions (record, approve, save).
- **Focus (keyboard / VoiceOver):** 2pt gold ring, `2pt` offset.
- **Disabled:** 40% opacity, no shadow, no haptic.

### Motion

- **Easing:** `cubic-bezier(0.32, 0.72, 0, 1)` (iOS standard "smooth") for entries; `cubic-bezier(0.4, 0, 0.2, 1)` for state changes.
- **Durations:** 200ms (micro), 320ms (sheets/transitions), 500ms (page).
- **No bounces.** No spring overshoots. No fades-from-blur.
- The progress bar in profile setup animates `width` over 320ms with a soft ease.
- The record button has a 1.6s breathing pulse while recording (gold halo, `box-shadow` only — never scales the button).

### Transparency & blur

- iOS system materials (`.thinMaterial`, `.regularMaterial`) on the tab bar and bottom sheets only.
- Custom blurs are **forbidden** in card chrome. They cheapen the surface.

### Imagery

- The only imagery is **avatars** (initials on a gold radial gradient, white text).
- No stock photography. No hero illustrations. No icons-as-mascots.
- Country flags on the language picker are the **only** decorative iconography.

### Layout rules

- **Fixed top bar** on all main tabs (44pt iPhone / 50pt iPad).
- **Fixed bottom tab bar** (49pt + safe area).
- **Sheets dismiss downward** with a grabber. Never use a top-right "Close" X.
- **iPad ≥1024w:** split view (sidebar 320pt + detail). Otherwise stack and drill-down.
- **Safe areas honored** everywhere — content never crosses the home indicator or notch.

---

## Iconography

Aurion's icon language is **SF Symbols** — the system set Apple ships with iOS. SF Symbols carry the right weight, optical alignment, and accessibility plumbing for an iOS-first product, and they automatically respect Dynamic Type, weight, and color modes.

### What we use

The brief specifically calls out these SF Symbols by name:
- `person.2` — encounter type: doctor + patient
- `person.3` — encounter type: with team member
- `graduationcap` — encounter type: with trainee
- `lock.shield` — consent overlay
- `mic`, `camera`, `dot.radiowaves.left.and.right` — capture stream indicators
- `doc.text` / `doc.text.fill` — note-ready states
- `checkmark`, `checkmark.circle.fill` — selection, completion
- `chevron.right`, `chevron.left` — navigation
- `pause.fill`, `stop.fill`, `circle.fill` — recording controls

Tab bar uses filled variants on the active tab, outline on inactive — standard iOS pattern.

### Web substitution

Web previews of this design system use **[Lucide](https://lucide.dev)** as a CDN-hosted stand-in for SF Symbols (similar 1.5–2px stroke weight, comparable optical sizing). Lucide is loaded from `https://unpkg.com/lucide@latest`. **This is a substitution; production iOS code uses SF Symbols directly via `Image(systemName:)`.**

| SF Symbol | Lucide stand-in |
|---|---|
| `person.2` | `users` |
| `person.3` | `users-round` |
| `graduationcap` | `graduation-cap` |
| `lock.shield` | `shield-check` |
| `mic` | `mic` |
| `camera` | `camera` |
| `doc.text` | `file-text` |
| `chevron.right` | `chevron-right` |
| `pause.fill` | `pause` (filled via CSS) |
| `stop.fill` | `square` (filled via CSS) |

### Logo & marks

- `assets/logo-mark.svg` — gold hexagon mark only (64×64 base)
- `assets/logo-lockup.svg` — mark + "Aurion / CLINICAL AI" wordmark for light backgrounds
- `assets/logo-lockup-dark.svg` — same lockup for dark / navy backgrounds
- `assets/app-icon.svg` — iOS app icon (squircle 256×256 base, gold gradient hex on navy)
- `assets/avatar-sample.svg` — initials avatar pattern (gold radial gradient, white text)

### Country flags (only decorative iconography)

The language picker (English / Français) shows real country flags. Web previews use the [`flag-icons`](https://github.com/lipis/flag-icons) CSS package via CDN (`<span class="fi fi-us">`, `<span class="fi fi-fr">`).

### Rules

- **No emoji** in product UI. Ever.
- **No custom illustrated icons.** If SF Symbols doesn't have it, we don't use it.
- **No icon-only buttons** without a 44pt hit target.
- Icons in body copy run at the same `cap-height` as the surrounding text.
- Icon weight matches text weight: regular text → `.regular`, semibold buttons → `.semibold`.

---

## Type substitution

The system specifies **SF Pro** — Apple's system font, free on Apple platforms but not freely redistributable for the web. For web previews and design tooling, we use **Inter** (Google Fonts) as the closest open-source match. Inter is loaded via:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

**This is a substitution; production iOS code uses SF Pro directly.** If you have licensed SF Pro web fonts, drop the `.woff2` files into `fonts/` and update the `--font-display` / `--font-text` CSS variables.

`JetBrains Mono` is the substitute for `SF Mono` (recording timer, code blocks).

---

## UI kits

| Kit | Path | Notes |
|---|---|---|
| iOS app | `ui_kits/ios/` | 12 core screens wired as a click-thru prototype |

## Index of preview cards

The Design System tab assembles a card per file in `preview/`. Cards are grouped:

- **Type** — display, body, mono, type scale
- **Colors** — navy ramp, gold ramp, neutrals, semantic
- **Spacing** — radii, shadow, spacing scale
- **Components** — buttons, badges, cards, inputs, sheets
- **Brand** — logo, avatar, app icon


# Aurion design system — canonical spec for every Stitch prompt

Aurion Clinical AI is a wearable multimodal AI physician-assistant. The web portal is **premium,
clinical-grade, calm, and precise** — generous whitespace, quiet confidence, never flashy or
consumer-gimmicky. It must read as the same product as the iOS app (identical palette) and stay
**consistent across every screen** (shared shell, header, cards).

Source of truth in code: `web/tailwind.config.ts`, `web/app/globals.css`, `web/lib/accent.ts`,
`web/components/AurionLogo.tsx`, `web/components/Sidebar.tsx`.

## Logo — NEVER fake, redraw, recolor, or substitute
- **Mark:** a navy rounded-square (squircle) icon containing a gold "A" with a small comet + star.
  File: `/brand/aurion-icon.png`.
- **Full lockup:** the mark + "Aurion" wordmark + tagline *"the gold standard in clinical AI"*, set
  on a navy field. File: `/brand/aurion-logo-full.png`. Used on the login hero.
- In Stitch: **treat the logo as a fixed placeholder image** ("Aurion logo — existing asset, do not
  modify"). Do not generate a new logo, monogram, or icon. Pixel-identical to iOS.

## Color (light mode; dark-mode tokens exist but ship light)
| Token | Hex | Use |
|---|---|---|
| canvas | `#F5F6FA` | page background |
| surface / card | `#FFFFFF` | cards, panels |
| hairline | `#E6E9EE` | quiet dividers / borders |
| navy.700 (brand) | `#0C1B37` | primary text, dark chrome, sidebar logo chip |
| navy.600 / .800 | `#16284E` / `#081226` | gradient stops (navy hero) |
| **gold.500 (accent)** | `#C9A84C` | primary buttons, active nav, interactive highlights |
| gold.300 / .600 | `#E5D082` / `#B5953D` | gold gradient / hover |
| text secondary | `~#6B7280` | sub-labels, metadata |
| **amber** | `#D9941F` | warnings · **CONFLICTS** (fixed) |
| **green** | `#2E9E6A` | success · masking pass · approved (fixed) |
| **red** | `#D9352B` | error · masking fail · critical alerts (fixed) |
| **blue** | `#2D6CDF` | info · neutral badges (fixed) |

### Accent theming (important)
Gold is the **default** accent, but physicians can pick teal `#14B8A6` / indigo `#6366F1` /
rose `#F43F5E` / slate `#64748B`. **Design with gold**, and apply the accent only to *interactive /
brand* highlights (primary buttons, active nav, focus rings, selected chips). **Compliance & status
colors (amber/green/red/blue, navy) are NEVER accent-themed** — they stay fixed so safety signals
read identically for every user.

## Typography — Inter (headings tight-tracked)
large-title 34px/700 · display 28/700 · title 22/600 · title-3 20/600 · headline 17/600 ·
body 17 · callout 15/500 · caption 13 · micro 11/600 UPPERCASE + letter-spacing (eyebrows).

## Shape, depth, motion
- Radius: card 16px · button 12px · chip 10px · sheet/modal 20px · small 6px.
- Shadow: soft 2-layer card shadow (`0 1px 2px rgba(12,27,55,.04), 0 6px 18px -6px rgba(12,27,55,.08)`);
  primary gold button carries a subtle gold glow.
- Motion: 320ms `cubic-bezier(0.32,0.72,0,1)` fade-in / slide-up; staggered card entrances.

## Shared chrome (every authed page)
- **Left Sidebar** (collapsible, persists width): Aurion squircle mark + "Portal"/"Admin" eyebrow at
  top; role-filtered nav with line icons + active state (gold tint + left indicator); clinicians get
  a ⌘K search row; bottom: user avatar chip (gold), accent picker (clinician), theme toggle, locale
  switcher (EN/FR), sign out.
- **Top-right NotificationBell** (unread dot + dropdown) on every portal page.
- **Page header pattern:** micro UPPERCASE eyebrow → large-title H1 → optional one-line description,
  with primary/secondary actions right-aligned. Optional breadcrumb above on detail pages.
- **Cards** on canvas with the soft shadow + 16px radius. **Status badges** = pills, semantic-tinted.
- **Primary button** = gold fill / navy text / gold glow. **Secondary** = white w/ navy text + hairline.
- **Tables**: quiet hairline rows, sticky header, hover row tint, short code-style IDs in mono chips.
- **Empty states**: centered line icon in a soft circle + title + one-line hint + (optional) action.
- **Loading**: shimmer skeletons matching the final layout.

## Content rules
- Bilingual EN + FR — never assume English text length; design flexible widths and wrapping.
- No PHI on screen unless the route is owner-scoped (patient detail); keep document titles generic.
- Keep it information-dense but breathable — clinicians scan fast.

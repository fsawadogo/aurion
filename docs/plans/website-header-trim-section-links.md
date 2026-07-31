# Website: remove section-anchor links from the marketing-site header

**Branch:** `lane-website/header-trim-section-links` · **Lane:** website (peritwin.ai / peritwin.com marketing site — NOT the `web/` portal)

## Why

Uzziel (2026-07-31, screenshot of peritwin.ai/en): the top menu still shows the
four in-page section links — Patient journey, Platform, Dashboard, Digital
Colleague — and they need to go. The sections themselves stay on the landing
page as scrollable content; no replacement navigation is added anywhere.

## Current state

`website/components/landing/landing-header.tsx` renders two link groups:

- `SECTIONS` (lines 14–19): `#continuum` → Patient journey, `#platform` →
  Platform, `#workbench` → Dashboard, `#colleague` → Digital Colleague.
  Rendered twice — a desktop `<nav>` (xl breakpoint) and the top block of the
  mobile hamburger drawer.
- `PAGE_LINKS` + distinct renders: Partners, Pilots, Physician portal,
  LanguageSwitcher (EN/FR), Contact us. **These stay.**

The header is mounted once in `website/app/[locale]/layout.tsx`, so every page
(landing, partners, pilots, contact) shares it. On subpages the anchor links
were dead ends anyway (no such ids off the landing page).

The four labels come from `nav.continuum|platform|workbench|colleague` in
`website/messages/{en,fr}/common.json` — used **only** by the header (grep
verified). The footer's similar-looking links use separate
`footer.platform.*` keys.

## Change

1. `website/components/landing/landing-header.tsx` — delete the `SECTIONS`
   array, its desktop `<nav>` block, and its mobile-drawer block (list items +
   the divider that separated sections from page links, so the drawer doesn't
   open with a floating rule).
2. `website/messages/en/common.json` + `website/messages/fr/common.json` —
   remove the four now-orphaned `nav.*` keys (`continuum`, `platform`,
   `workbench`, `colleague`).

## Explicitly out of scope

- Landing-page section components (`continuum-section` etc.) — content stays,
  per Uzziel: "Just leave them in the landing page no need to add the
  navigation."
- `landing-footer.tsx` — its Platform column also links these anchors, but the
  instruction was the top menu only; footer untouched.
- The redesign branch `backup/website-redesign-for-peritwin-ai` — this change
  targets `main`, which is what's live per #698.

## Acceptance criteria

- AC-1: Header (desktop + mobile drawer) shows only: wordmark, Partners,
  Pilots, Physician portal, language switcher, Contact us.
- AC-2: No reference to the removed `nav.*` keys or a header `SECTIONS`
  array remains anywhere in `website/`.
- AC-3: Landing page still renders all four sections with their `id`
  anchors intact (footer links keep working).
- AC-4: EN and FR common.json stay key-for-key parallel.

## Gates (website lane)

- `pnpm lint` (eslint) clean for the touched files.
- `pnpm build` — static export green, same 17/17 pages as #698's baseline.

Then verify-receipt JSON → /simplify (4 agents) → PR via §9. Uzziel merges.

---
name: aurion-design
description: Use this skill to generate well-branded interfaces and assets for Aurion Clinical AI, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

Key files:
- `README.md` — brand voice, visual foundations, content rules, iconography
- `colors_and_type.css` — design tokens (color, type, spacing, radii, shadow, motion)
- `assets/` — logo marks, app icon, avatar pattern
- `preview/` — at-a-glance design system cards
- `ui_kits/ios/` — full iOS UI kit (components.jsx + screens.jsx + index.html)

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. The iOS UI kit's `components.jsx` and `screens.jsx` are the canonical source for any iOS screen you build — import them rather than redrawing.

If working on production code, copy assets and read the rules here to become an expert in designing with this brand. SF Pro is the production typeface (Inter is the web substitute); SF Symbols is the production icon set (Lucide is the web substitute).

If the user invokes this skill without any other guidance, ask them what they want to build or design (a new screen, a marketing asset, a slide deck, etc.), ask some scoping questions (surface, audience, scope, fidelity), and act as an expert designer who outputs HTML artifacts or production code, depending on the need.

Brand in one line: **calm, confident, minimal — luxury medical device, not hospital software.** Navy + gold. SF Pro. No emoji in product UI. No marketing-speak.

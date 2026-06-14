# Stitch prompt — App entry splash (`/`)

**Generate the brief branded splash/loading screen shown at the app root** while Aurion checks the
session and redirects (to the role-appropriate dashboard, or to sign-in). Full-screen, no sidebar or
chrome — this is pre-shell.

**Layout:** a full-bleed deep **navy radial gradient** (center `#16284E` → `#0C1B37` → edges
`#081226`). Centered: the **Aurion full logo lockup** (the existing brand mark — a navy squircle with
a gold "A" + comet/star — plus the "Aurion" wordmark and tagline "the gold standard in clinical AI")
with a **soft, slowly-pulsing gold glow** behind it. Below the lockup, a quiet loading indicator: a
thin gold (`#C9A84C`) progress shimmer or a small centered spinner. Nothing else — calm, premium,
momentary.

**States:** the single loading state (optionally a faint "Loading your workspace…" caption that
supports EN/FR).

**Important — logo:** use the existing Aurion logo lockup as a **fixed placeholder image**; do NOT
invent, redraw, recolor, or substitute it.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade. Navy `#0C1B37` field with gradient stops `#16284E`/`#081226`; gold `#C9A84C` accent (glow + loader); Inter typeface. Soft, subtle motion (320ms `cubic-bezier(0.32,0.72,0,1)`, gentle gold glow pulse). Bilingual-ready (EN/FR). Must match the Aurion login hero + iOS launch aesthetic exactly — same brand, same navy + gold.

# Stitch prompt — Portal entry splash (`/portal`)

**Generate the brief branded splash shown at `/portal`** while the app routes the signed-in user
into their portal dashboard. Full-screen, no sidebar — momentary transition screen. Visually
consistent with the app-root splash (`04`), just the in-app entry moment.

**Layout:** full-bleed deep **navy radial gradient** (`#16284E` → `#0C1B37` → `#081226`). Centered:
the **Aurion squircle mark** (existing brand icon — navy squircle, gold "A" + comet/star) with a soft
pulsing gold glow, the "Aurion" wordmark beneath, and a quiet **"Portal"** eyebrow (micro, uppercase,
tracked). Below, a thin gold (`#C9A84C`) loading shimmer / small spinner. Optionally a faint
"Loading your workspace…" caption (EN/FR). Calm, premium, brief.

**States:** single loading state.

**Important — logo:** use the existing Aurion mark as a **fixed placeholder image**; do NOT invent,
redraw, recolor, or substitute it.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade. Navy `#0C1B37` field with gradient stops `#16284E`/`#081226`; gold `#C9A84C` accent (glow + loader); Inter typeface, micro-11 uppercase eyebrow. Soft gold-glow pulse, 320ms `cubic-bezier(0.32,0.72,0,1)`. Bilingual-ready (EN/FR). Consistent with the app-root splash (04) + the rest of the Aurion portal + iOS app.

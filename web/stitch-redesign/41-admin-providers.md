# Stitch prompt — AI providers, runtime switch (`/portal/admin/providers`)

**Generate the runtime AI-provider switch screen** — override the active provider per pipeline stage,
with usage + A/B quality comparison.

**Layout (single column):**
1. **Header** — eyebrow, H1 "AI providers", subtitle.
2. **Per-stage selector cards** (Note generation · Vision · Transcription): title + description +
   **pill options** (active = gold fill, others = navy outline). A status line shows the AppConfig
   baseline vs the current override, and a "Reset to default" button appears only when overridden.
3. **Usage panel** — range picker (24h / 7d / 30d / all) + summary stat cards (calls, success %,
   avg latency, est. cost) + a per-provider table.
4. **Compare panel** — pick a stage + A vs B providers + range; an operational table (calls, success,
   fallback, latency, cost) and a quality table (overall / accuracy / citation / compliance /
   hallucination scores per provider).

**States:** loading · empty (usage) · error · role-gated (quality hidden for compliance officer).
**Compliance/safety:** show baseline-vs-override clearly; provider choice is traceability.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (active provider pill); FIXED semantic green/amber/red/blue for status + metrics (never themed). Inter type; 16px cards + soft shadow; pill selectors; metric tables. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

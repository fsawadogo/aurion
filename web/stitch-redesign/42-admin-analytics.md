# Stitch prompt — Analytics, adoption & ROI (`/portal/admin/analytics`)

**Generate the adoption/ROI analytics screen** — usage, quality, and an opt-in time-saved estimate.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Analytics", description, **Export CSV** (right).
2. **Controls** — range buttons (7d / 30d / 90d / all) + a "minutes per note" baseline input (1–120,
   clock icon) that powers the time-saved estimate.
3. **Adoption stat cards** (4-up): Active clinicians · Notes exported · Notes per active day ·
   **Time saved** (with a small footnote "assumes {baseline} min/note" when a baseline is set).
4. **Quality cards** (4-up): Completeness · Citation traceability · Edit rate · Stage-1 latency.
5. **Per-clinician table:** clinician (email/ID) · sessions · exported · notes/day · avg completeness ·
   avg edit rate · time saved · last active (relative).

**States:** loading skeleton · empty table · error.
**Compliance/safety:** time-saved is an **opt-in estimate** with a visible assumption footnote — never present it as a hard measured fact.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description, action right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (figures); FIXED semantic green/amber/red/blue (never themed). Inter type; 16px cards + soft shadow; stat cards + table. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

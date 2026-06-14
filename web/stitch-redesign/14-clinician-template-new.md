# Stitch prompt — New template (`/portal/templates/new`)

**Generate the "create a note template" screen** with two build modes.

**Layout:** breadcrumb (Templates › New) + header (H1 "New template", description). A **mode toggle**
(Manual / AI) below the header. Then one of:
- **Manual mode:** a card with a structured **section editor** (add/remove sections; per section: a
  label, type, and fields), a live preview, an inline validation alert, and a primary gold "Save".
- **AI mode (two columns):** left a **conversational chat** (message bubbles, input textarea, send
  button, busy spinner) to describe the template; right a **live draft preview** that updates as the
  AI proposes structure, with a primary gold "Finalize" button. Placeholder hint before any draft.

**States:** bootstrapping skeleton (AI) · empty draft hint · validating (alert) · saving · success (→ template detail).

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → breadcrumb. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed). Inter type; 16px cards + soft shadow; gold primary button. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

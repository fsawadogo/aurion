# Stitch prompt — Macros (`/portal/macros`)

**Generate the phrase-macros manager** — text shortcuts a clinician expands while editing notes.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Macros", description, primary gold "New macro".
2. **Macro list card** — each row: the shortcut in a **gold-tinted mono chip** (e.g. `/ros`), a
   2-line body preview, an optional specialty badge, and Edit / Delete actions.
3. **Empty state** — a zap/lightning line icon, message, "Add your first macro".
4. **Macro editor modal** — title (New/Edit), a monospace shortcut input (starts with `/`), a body
   textarea (resizable), a specialty dropdown (All / specialties), inline error, Cancel + gold Save.

**States:** loading skeleton · empty · list · editing (modal) · saving · delete-confirm · error.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description, action right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed). Inter type, mono for shortcuts; 16px cards + soft shadow; gold primary button; 20px modal radius. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

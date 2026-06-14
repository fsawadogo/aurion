# Stitch prompt — System templates (`/portal/admin/templates`)

**Generate the admin system-templates editor** — edit the bundled specialty templates; Save writes a
runtime override (fleet-wide ~10s); Revert restores the on-disk default.

**Layout (single column):**
1. **Header** — eyebrow, H1 "System templates", description.
2. **Card with an expandable template list:** each row = grid icon + display name + `template_key`
   (mono) + version · N sections + an **"override" badge** when overridden. Selecting one expands a
   **section editor** below (per section: name, description, required flag, visual-trigger keywords).
3. **Action bar:** ghost red "Revert" (only when overridden, opens confirm modal) + primary gold "Save".
4. A small **live-state hint** under the editor: "Live override" vs "Live default".

**States:** loading (list/detail skeleton) · empty · busy (save/revert) · success · error · revert-confirm modal.
**Compliance/safety:** `template_key` is immutable; Save is **audited**; Revert is destructive (modal warns).

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (Save, active row); FIXED semantic green (success), red (revert/destructive), blue (override badge) (never themed). Inter type, mono key; 16px cards + soft shadow; 20px modal. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

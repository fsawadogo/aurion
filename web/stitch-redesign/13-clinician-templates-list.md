# Stitch prompt — Templates list (`/portal/templates`)

**Generate the clinician's note-templates manager** — their custom specialty templates plus
shared/system ones.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Templates", description, two actions right: "Upload" (file → AI extracts)
   and primary gold "New template".
2. **Template list card** — quiet rows, hover tint. Each row: a grid/template line icon, display name,
   `template_key` in a mono chip, metadata (version · N sections · "updated 3d ago"), a **"Shared"
   badge** (blue) when applicable, and inline actions: Open (pencil) and Delete (trash, owner-only).
3. **Empty state** — "Start building your first template" with a primary action.

**States:** loading skeleton; empty; delete-confirm modal (cancel / destructive confirm); red error.
**Note:** Delete only appears for templates the clinician owns.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description, actions right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber `#D9941F`/green `#2E9E6A`/red `#D9352B`/blue `#2D6CDF` (never themed). Inter type; 16px cards + soft shadow; gold primary button; mono key chips; semantic badges. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

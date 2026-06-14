# Stitch prompt — Template detail (`/portal/templates/[id]`)

**Generate the template view/edit screen.** Breadcrumb (Templates › name) + header (H1 = template
name, metadata: key · version · N sections).

**Layout:** a **mode tab group** — Preview / Edit / JSON:
- **Preview:** read-only rendered template (sections + fields).
- **Edit:** the structured section editor (add/remove/edit sections) + Save + inline validation alert.
- **JSON:** a monospace code textarea of the raw template with inline parse-error feedback + Save.
A floating footer holds the mode tabs, an **Export** (download) button, and an owner-only **Delete**
(red, trash) that opens a confirm modal.

**States:** loading skeleton · per-mode views · saving · deleting (→ list) · not-found · shared/non-owner = preview only.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → breadcrumb. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed). Inter type, mono for JSON; 16px cards + soft shadow; gold primary button. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

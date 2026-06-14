# Stitch prompt — Profile / practice settings (`/portal/profile`)

**Generate the clinician practice-settings screen** — a sectioned settings form with a sticky save bar.

**Layout (single column of section cards):**
1. **Header** — eyebrow, H1 "Profile", description, secondary "Account settings" button (right).
2. **Identity card** — display-name field.
3. **Practice card** — practice-type multi-select (pill chips, active = gold), primary-specialty
   dropdown, a consultation-types editor (add/remove custom labels), and a visit-type → contexts
   editor (each context can pick a template).
4. **Recording card** — retention-days number (1–30), an auto-upload toggle (gold when on), a
   consent-reprompt frequency dropdown.
5. **Appearance card** — **accent-color picker**: five swatch chips (gold default, teal, indigo,
   rose, slate) that re-theme the interactive accent instantly. Show that compliance/status colors do
   NOT change with the accent.
6. **Sticky bottom save bar** — "Unsaved changes / All saved" label + Discard + primary gold Save.

**States:** loading skeleton · clean (save disabled) · dirty (save enabled) · saving · saved (green, auto-dismiss) · error.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description, action right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (the themeable accent shown in the picker); FIXED semantic amber/green/red/blue stay constant regardless of accent. Inter type; 16px cards + soft shadow; gold primary button; pill toggles. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

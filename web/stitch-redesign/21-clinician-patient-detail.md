# Stitch prompt — Patient encounters (`/portal/patients/[identifier]`)

**Generate the per-patient longitudinal view** — every session for one patient identifier.

**Layout (single column):**
1. **Header** — breadcrumb "Back to inbox", eyebrow, H1 = the patient identifier, description with
   total count + first/last visit dates; Refresh (right).
2. **Stat tiles** (3-up): Total sessions (history icon), Last visit (relative, clock), Most recent
   specialty (stethoscope).
3. **Session list card** — header "Sessions"; rows: specialty, relative date, short session-ID mono
   chip, optional external-reference badge, state badge, chevron → opens the note. Empty state with
   an id-card line icon.

**States:** loading (skeleton tiles + list) · empty · loaded · error (banner + retry).
**Compliance/safety:** the identifier is in the URL but the route is owner-scoped to the clinician;
keep the browser/document title generic ("Patient encounters") so the identifier never leaks to
history; never show other PHI.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → breadcrumb + description, Refresh right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed). Inter type, mono ID chips; 16px cards + soft shadow; stat tiles + semantic state pills. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

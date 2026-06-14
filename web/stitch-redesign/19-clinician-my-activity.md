# Stitch prompt — My activity / self-audit (`/portal/audit`)

**Generate the clinician's own activity log** — a read-only, self-scoped audit of their actions.

**Layout (single column):**
1. **Header** — eyebrow, H1 "My activity", description.
2. **Filter bar** (card, sticky): date-from, date-to, an event-type dropdown, a session-ID search,
   and a CSV export button (current page).
3. **Event table** (50/page, sticky header): columns Timestamp · Actor · **Event type badge**
   (semantic color by category) · Session-ID (mono chip, links to the note) · Details summary.
4. **Pagination footer** — Prev / Next + "Page X of Y".

**States:** loading skeleton rows · loaded · filtering (refetch) · exporting · empty · error.
**Compliance/safety:** this log is self-scoped (only the clinician's own events); present it as a
trustworthy, append-only record.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic (never themed) blue `#2D6CDF`=info, green `#2E9E6A`=success, amber `#D9941F`=warning, red `#D9352B`=error. Inter type, mono ID chips; 16px cards + soft shadow; sticky-header table; semantic event pills. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

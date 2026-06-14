# Stitch prompt — Notes / Sessions inbox (`/portal/notes`)

**Generate the clinician's notes inbox** — a filterable list of all their sessions, with multi-select
bulk export.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Notes", one-line description, Refresh.
2. **Filter bar** (in a card, sticky top): status chips (All / Pending / Completed / Exported),
   a date dropdown (All / Today / 7 days / 30 days), and a search input.
3. **Selection toolbar** (only when exportable rows exist): "N selected", Select-all / Clear, and a
   primary gold **Export** button (download icon) → bundles selected notes as DOCX.
4. **Session list** — quiet hairline rows, hover tint. Each row: checkbox (exportable only), specialty,
   optional patient-identifier badge, relative created date, short session-ID mono chip, and a
   **state badge** (info = recording/paused/processing, warning = awaiting review, success =
   approved/exported, neutral = purged, error = failed), chevron at the end.

**States:** loading skeleton (≈6 rows); empty "No sessions match your filters"; red error.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav, ⌘K) + top-right notification bell; header = uppercase eyebrow → H1 → description, actions right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber `#D9941F`/green `#2E9E6A`/red `#D9352B`/blue `#2D6CDF` (never themed). Inter type; 16px cards + soft shadow; gold primary button; tables with sticky header + mono ID chips + semantic state pills. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

# Stitch prompt — Session timeline (`/audit/[sessionId]`)

**Generate the per-session audit timeline** — the chronological event history for one session.

**Layout:**
1. **Header** — H1 "Session timeline" + event count; "Back to audit log" button.
2. **Summary card** (3-up): Session (mono, full ID) · First event (timestamp) · Last event (timestamp).
3. **Timeline card** — "Chronological events · earliest at top". A vertical timeline with a left rail
   and **ring-colored dots** keyed to each event's semantic variant. Each item: time (HH:MM:SS),
   **event badge** (humanized), "by {actor role}", date, and an expandable key:value details block
   (quiet, scrollable).

**States:** loading · error · empty "No audit events for this session" · loaded.
**Compliance/safety:** append-only, chronological, immutable record; semantic dot/badge colors fixed.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1, back button. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic green `#2E9E6A`/amber `#D9941F`/red `#D9352B`/blue `#2D6CDF`/navy-neutral for timeline dots + badges (never themed). Inter type, mono ID; 16px cards + soft shadow. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

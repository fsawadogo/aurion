# Stitch prompt — Operational alerts (`/portal/admin/alerts`)

**Generate the operational-alerts screen** — pipeline alerts (stage failures, masking issues, SLA
breaches) that admins acknowledge.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Alerts", description.
2. **Filter pills** — Open (active) / Acknowledged / All.
3. **Alert list card** — each row: a **severity badge** (critical = red, warning = amber, info = blue),
   the message, `alert_type` (mono), source, created (relative), acknowledged-by/at (relative) when
   present, and an "Acknowledge" button (only while open).
4. **Empty state** — a bell line icon in a soft **green** circle, "No open alerts".

**States:** loading skeleton · empty · error.
**Compliance/safety:** severity colors are fixed semantic; acknowledgement captures who/when.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (Acknowledge); FIXED semantic red `#D9352B`=critical, amber `#D9941F`=warning, blue `#2D6CDF`=info, green `#2E9E6A`=all-clear (never themed). Inter type, mono type chips; 16px cards + soft shadow; filter pills + severity badges. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

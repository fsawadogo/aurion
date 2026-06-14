# Stitch prompt — Compliance reports (`/portal/admin/compliance`)

**Generate the compliance-reports screen** — generate, list, and download signed (SHA-256) CSV
snapshots for audit trail, Law-25 masking proof, and retention lifecycle.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Compliance reports", description.
2. **Generate button group** — three secondary buttons: Audit · Masking · Retention (spinner on the
   active type; all disabled while one is generating).
3. **Reports table** — each row: a **type badge** (blue), generated-at (relative), window
   (since…until or "full history"), file size (KB/MB), the **SHA-256 prefix** in a mono chip, and a
   **Download** button.
4. Success alert (green) on generate showing the SHA-256 prefix; red error on failure.
5. **Empty state** — "No reports generated yet".

**States:** loading · empty · generating (per-type spinner) · error.
**Compliance/safety:** the **SHA-256 hash** is the integrity proof — show it prominently (table + success
toast); reports are signed regulatory artifacts. Keep hash/type chips in fixed colors.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic blue `#2D6CDF`=type, green `#2E9E6A`=success/hash, red `#D9352B`=error (never themed). Inter type, mono for SHA-256 prefixes; 16px cards + soft shadow; table + button group. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

# Stitch prompt — PHI masking validation (`/masking`)

**Generate the PHI-masking validation screen** — pass/fail of on-device face/PHI masking across
sessions. The pass rate is a top compliance signal (target 100%).

**Layout (single column):**
1. **Header** — eyebrow, H1 "PHI masking validation", subtitle "100% pass-rate target".
2. **Date filter card** — From / To.
3. **Summary cards** (4-up): Total sessions (navy figure) · Passed (green) · Failed (red if >0 else
   muted) · **Pass-rate ring** — a circular progress ring, **green at 100%, red below**, with
   "X% Pass rate" centered.
4. **Per-session table:** Session (mono chip) · Clinician (avatar+name) · Date · Attempts (frames) ·
   Masked (green) · Failed (red if >0) · Skipped (amber if >0) · Uploaded · **Status** (Pass/Fail
   badge with icon). Row → session timeline.
5. **Empty state** — shield-check line icon, "No masking data yet".

**States:** loading skeleton · empty · error.
**Compliance/safety:** this whole screen is a safety surface — pass rate, pass/fail, and the ring use
**fixed** green/red (never accent-themed); 100% is the bar.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic green `#2E9E6A`=pass/masked, red `#D9352B`=fail, amber `#D9941F`=skipped (never themed). Inter type, mono ID; 16px cards + soft shadow; circular progress ring; status pills. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

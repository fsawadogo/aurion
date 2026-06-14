# Stitch prompt — Captured media review (`/portal/media`)

**Generate the captured-media retention screen** — sessions whose raw audio + masked clips are still
inside the retention window, with a countdown and gated downloads. **PHI-safe: no patient identifier
anywhere.**

**Layout (single column):**
1. **Header** — eyebrow, H1 "Captured media", description (mentions the retention-days window),
   Refresh (right).
2. **View-only banner** (navy, lock icon) for compliance officers: "You can view but not download".
3. **Table:** Physician (avatar + name — NOT the patient) · Date · Visit (visit type + context) ·
   Encounter (type) · **State badge** · **Media** (audio icon + count, clip icon + count, or "none") ·
   **Expires** (countdown: "in X days/hours" or "expired") · Actions (Download audio / Download clips —
   only for admin/eval; hidden for compliance).
4. **"Not enabled" empty state** — a film line icon + hint, shown when the retention flag is off.

**States:** loading skeleton · empty · not-enabled · per-row download error · role-gated (downloads hidden).
**Compliance/safety (prominent):** **never show a patient identifier**; the retention **countdown** is
a hard deadline; downloads are double-gated (role + flag); "audio is unmasked patient speech" implies
PHI — surface that caution. Keep the view-only/lock chrome in fixed navy.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description, Refresh right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37` (view-only/lock banner), accent gold `#C9A84C` (download buttons); FIXED semantic amber `#D9941F`=expiring, red `#D9352B`=expired/error, green/blue (never themed). Inter type; 16px cards + soft shadow; state pills + countdown chips. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

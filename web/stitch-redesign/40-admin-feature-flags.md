# Stitch prompt — Feature flags (`/portal/admin/feature-flags`)

**Generate the admin feature-flags screen** — toggle the post-pilot iOS note-review card flags at
runtime (no redeploy).

**Layout (single column):**
1. **Header** — eyebrow, H1 "Feature flags", description.
2. **Card** with a "Editable cards" section header (gold flag icon) and **per-flag toggle rows:**
   each row = flag display name + one-line description + a **toggle switch** (gold ON / navy OFF) +
   a small "changed" dot when dirty. Editable flags: orders card, coding & billing card, patient
   summary card, EMR write-back card. (Optionally show the other flags read-only/dimmed.)
3. **Action bar:** ghost "Reset" + primary gold "Save" — both disabled until something is dirty.
4. Success alert (green) after save **including the AppConfig version number**; red error on failure.

**States:** loading skeleton · clean (buttons disabled) · dirty · saving (optimistic) · success (version badge) · error (rolls back).
**Compliance/safety:** changes are audited + push fleet-wide (~30s) — show the version on success.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → description. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (ON toggle, Save); FIXED semantic green `#2E9E6A` (success+version), red `#D9352B` (error) (never themed). Inter type; 16px cards + soft shadow; pill toggles. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

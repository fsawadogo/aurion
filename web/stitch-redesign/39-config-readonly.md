# Stitch prompt — Configuration, read-only (`/config`)

**Generate the read-only runtime-config screen** — live AppConfig state + a change-history audit.
(Currently plain + not localized — elevate + make EN/FR-ready.)

**Layout (single column):**
1. **Header** — eyebrow, H1 "Configuration", subtitle "Read-only AppConfig state".
2. **Four cards (2×2):** Active providers (transcription / note-generation / vision — provider name
   chips) · Model parameters (temperature, max-tokens, confidence threshold, grouped by stage) ·
   Pipeline settings (skip window, frame windows, capture FPS — label/value rows) · Feature flags
   (read-only toggle switches, gold when on).
3. **Change-history table:** Timestamp (relative + tooltip) · Changed by (initials avatar + name) ·
   Previous (dotted-path = value diff, mono) · New (mono diff) · **Version badge** (v#).
   Empty state: history icon + "No configuration changes recorded yet".
4. Footer note: "Provider switching is available via the admin Providers page."

**States:** loading skeleton · empty history · error. Read-only (no edit controls).
**Compliance/safety:** the change history is an audit trail — clear who/when/what; version badges fixed.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (on-toggles); FIXED semantic blue `#2D6CDF` (provider/version chips), amber/green/red (never themed). Inter type, mono for values/diffs; 16px cards + soft shadow. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

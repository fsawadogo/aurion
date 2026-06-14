# Stitch prompt — Audit log (`/audit`)

**Generate the compliance audit-log screen** — the append-only, immutable session-lifecycle event
log with filters and CSV export.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Audit log", subtitle "Immutable session lifecycle events", **Export CSV**
   button (right, download icon).
2. **Filter card** — Session-ID search · From / To date pickers · Clinician text · Event-type dropdown
   (session_created, consent_confirmed, recording_started, stage1/stage2 events, note_exported,
   session_purged, masking_confirmed, config_changed, …).
3. **Paginated table** (50/page): Timestamp · Session (short ID mono chip) · **Event badge**
   (humanized + semantic color) · Details (PHI-free key:value summary, truncated w/ tooltip).
   Row click → session timeline.
4. **Pagination footer.**

**States:** loading · empty "No audit events match" · error.
**Compliance/safety:** convey **append-only / immutable** (this is a legal record); events are PHI-free
by design; keep event badges in fixed semantic colors.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle, action right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic (never themed) blue `#2D6CDF`/neutral/amber `#D9941F`/green `#2E9E6A`/red `#D9352B` for event badges. Inter type, mono ID chips; 16px cards + soft shadow; sticky-header table. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

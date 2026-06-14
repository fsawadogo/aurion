# Stitch prompt — Session completeness list (`/sessions`)

**Generate the admin/eval sessions table** — every session with its completeness score and provider
traceability.

**Layout (single column):**
1. **Header** — eyebrow, H1 "Session completeness", subtitle "Per-session scores and section coverage".
2. **Filter card** — inline: Clinician (text), Specialty (dropdown: Orthopedic / Plastic /
   Musculoskeletal / Emergency / General / All).
3. **Paginated table** (50/page): Session (short ID mono chip) · Clinician (avatar + name) ·
   Specialty · **State badge** · Sections (X / Y required) · **Completeness** (a thin progress bar —
   red below 90%, gold gradient at/above 90% — plus the %) · Provider (`provider_used`) · Created.
   Row click → session detail.
4. **Pagination footer** — "Page X of Y · N sessions" + Prev/Next.

**States:** loading skeleton · empty "No sessions found" · error banner.
**Compliance/safety:** the **provider** column is traceability — keep it; completeness bar uses fixed red/gold thresholds.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (completeness bar ≥90%); FIXED semantic amber/green/red/blue for state pills (never themed); red `#D9352B` for completeness <90%. Inter type, mono ID chips; 16px cards + soft shadow; sticky-header table. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

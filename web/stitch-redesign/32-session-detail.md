# Stitch prompt — Session detail (`/sessions/[id]`)

**Generate the admin/eval session-detail screen** — one session's completeness + per-section coverage.

**Layout:**
1. **Header** — H1 "Session detail" + clinician name + specialty; "Back to sessions" button.
2. **Summary card** (responsive 8-cell grid): Clinician (avatar+name) · Session ID (mono, full) ·
   State badge · Completeness (progress bar + %) · Sections (X / Y required) · Note version (v#, stage,
   approved flag) · Provider · Created / Updated (relative).
3. **Sections table** — "Per-section coverage against the {specialty} template; empty required
   sections are highlighted." Columns: Section (title + id) · Required/Optional · **Status badge**
   (populated / pending video / not captured / processing failed) · Claims (count) · **Source
   breakdown chips** (Transcript / Frame / Screen / Physician-edit counts). Required-but-empty rows
   tinted red.
4. Footer note linking to the Eval interface for masked transcript/frame review.

**States:** loading · error · not-found · loaded.
**Compliance/safety:** provider traceability; required-empty highlighting; status badges fixed semantic.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1, back button. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed); red tint for required-empty rows. Inter type, mono ID; 16px cards + soft shadow; semantic status pills + source chips. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

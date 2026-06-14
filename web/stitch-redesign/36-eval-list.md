# Stitch prompt — Evaluation list (`/eval`)

**Generate the model-evaluation master-detail screen** — eval-team reviewers browse sessions and
score note quality.

**Layout (two columns):**
1. **Header** — eyebrow, H1 "Evaluation", subtitle "Review sessions and score quality".
2. **Left pane (2/3)** — paginated table: Session (mono chip) · Clinician (avatar+name) · Specialty ·
   Assigned-to (email or "—", with a "done" badge if complete) · **Masked** (Yes/No badge —
   transcript+frames) · **Status** (Scored / Pending badge) · Score (overall %) · "Open triad" button.
   Selected row = gold tint.
3. **Right pane (1/3, sticky) — Quality scoring:** if already scored, a read-only display of
   transcript accuracy / citation correctness / descriptive-mode compliance / overall + notes; if
   unscored, three 0–100 **sliders** (color-coded), a notes textarea, and a "Submit score" button;
   if nothing selected, a placeholder.
4. **Pagination** under the table.

**States:** loading skeleton · empty "No sessions to evaluate" · error.
**Compliance/safety:** the **Masked Yes/No** badge and descriptive-mode-compliance score are safety
signals — keep them in fixed semantic colors.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (selected row, sliders); FIXED semantic green/amber/red/blue for Masked + Status badges (never themed). Inter type, mono ID; 16px cards + soft shadow; sticky right panel. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

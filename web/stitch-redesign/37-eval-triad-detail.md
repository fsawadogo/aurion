# Stitch prompt — Eval triad detail (`/eval/[id]`)

**Generate the deep evaluation "triad" screen** — three side-by-side panes for grading one session.

**Layout:** header "Eval — {clinician}" + specialty + back button. A **summary card** (6-up):
clinician · session · **Transcript Masked/Unmasked badge** · **Frames Masked/Unmasked badge** · note
version/stage · completeness % · Scored badge · Assigned-to (ADMIN sees a dropdown). Then the **triad**:
- **Transcript pane (left, ~4/12):** "PHI redacted upstream; visual-trigger segments highlighted in
  gold." Ordered segments: id mono chip, MM:SS→MM:SS range, a "trigger" amber badge when applicable,
  segment text; trigger/highlight rows tinted gold/amber.
- **Generated-note pane (center, ~5/12):** sections (title + status badge); each claim with clickable
  **source chips** (Transcript/Frame/Screen/Physician-edit + source-id) that scroll-highlight the
  transcript anchor; "edited" badge when physician-edited.
- **Frame-citations pane (right, ~3/12):** masked visual descriptions only ("the raw frames never
  leave the device") — citation cards with description, confidence, anchor.

Below: a **scoring panel** — descriptive-mode pass/fail, per-SOAP-section ratings, hallucination
count, discrepancies (one per line), notes, Submit.

**States:** loading · error · not-found · loaded.
**Compliance/safety (prominent, fixed colors):** masking badges, descriptive-mode pass, hallucination
count, "raw frames never leave the device" — all fixed semantic.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; dense but breathable. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1, back button. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (trigger highlights); FIXED semantic amber `#D9941F`=trigger/warning, green `#2E9E6A`=masked/pass, red `#D9352B`=unmasked/fail, blue `#2D6CDF`=info for badges + source chips (never themed). Inter type, mono ID/segment chips; 16px cards + soft shadow. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

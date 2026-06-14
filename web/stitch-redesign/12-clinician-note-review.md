# Stitch prompt — Note review, two-pane (`/portal/notes/[id]`)

**Generate the clinician note-review screen for the Aurion Clinical AI portal** — the core workspace
where a physician reviews, edits, resolves conflicts, and approves an AI-generated clinical note.
This is the most important screen; make it premium and calm under information density.

**Layout:** breadcrumb (Notes › specialty) + header (H1 = specialty). A floating inline
**patient-identifier editor** (text + save) top-right. A **Stage-2 progress banner** when visual
enrichment is running. Then a **two-column layout** (stacks on mobile):

- **Left pane — Sources:** an encounter-audio player card; the **transcript** with timestamped
  segments and **citation chips** (small source badges: T = transcript, V = visual, S = screen,
  M = measurement, E = physician edit). Clicking a claim's chip scroll-highlights its transcript anchor.
- **Right pane — the Note:** a **patient-summary card** (generated, editable); a **completeness ring**
  (% of required sections populated); **note section cards** (one per SOAP section — title, status
  badge, editable body, per-claim citation chips); a **conflict resolver** for any visual-vs-audio
  **CONFLICT** (three choices: accept visual / reject visual / edit) shown in **amber** and blocking
  approval until resolved; plus orders, coding-suggestions, and EMR-write-back cards where present.

**Primary actions:** Edit section (save/cancel), Resolve conflict, **Approve** (two-tap), Export DOCX.
**States:** skeletons; "no note yet"; conflicts-unresolved (approve disabled + amber banner); Stage-2 running; error.
**Compliance/safety (fixed colors, prominent):** CONFLICTS in **amber** must be explicit + block
approval; every claim shows a traceable source chip; patient identifier is treated as sensitive.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → breadcrumb, actions right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic (never themed) amber `#D9941F`=CONFLICTS/warning, green `#2E9E6A`=approved/populated, red `#D9352B`=error, blue `#2D6CDF`=info. Inter type; 16px cards + soft shadow; gold primary (Approve) button; status + citation chips. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

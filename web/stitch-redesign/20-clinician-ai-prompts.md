# Stitch prompt — AI Prompts transparency (`/portal/prompts`)

**Generate the AI-prompts transparency screen** — a read-only view of the exact LLM system prompts
the pipeline uses. The point is trust: show clinicians precisely what instructs the AI.

**Layout (single column):**
1. **Header** — eyebrow, H1 "AI Prompts", subtitle.
2. **Descriptive-mode callout** — a soft gold/amber info banner: "These are the exact instructions
   given to the AI — it describes what was observed, never diagnoses or interprets."
3. **Search input** — filter by name/purpose.
4. **Category sections** — grouped with a line-icon + label divider: Note · Vision · Extraction ·
   Preview. Within each, **prompt cards**: name, category, one-line purpose, and the full prompt body
   in a quiet scrollable monospace block (read-only).

**States:** loading skeleton · no-results empty · loaded · error.
**Compliance/safety:** prompts shown verbatim (transparency). Read-only — no editing.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed). Inter type, mono for prompt bodies; 16px cards + soft shadow. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.

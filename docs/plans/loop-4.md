# Plan — loop-4

## Task

loop-4 — redesign the clinician note-review screen (`/portal/notes/[id]`) to the Heidi-style single-column layout Uzziel approved in Claude Design, wired to the endpoints that already exist. No backend changes, no iOS impact.

## Why

Cohort 6 (2026-07-15 weekly). Two of Uzziel's assigned items are this screen:
- *"Corriger interface notes: regrouper les notes dans une seule zone de texte"* — one note block, transcript off the main screen.
- Faïçal, same meeting: *"le bouton de copie capture l'intégralité du contenu"* — Copy to EHR is the primary action.

The approved design is `docs/design/imported/note-review.dc.html`. The current page (`web/app/portal/notes/[id]/NoteReviewClient.tsx`) is a two-column transcript|cards layout with a bottom action bar.

## The governing rule

**The screen mirrors the note and the existing endpoints. It never formats the note (bullets/prose come from the prompt, not the UI), and it never shows a control that has no backend.** Everything below follows from that.

## Approach

Re-layout the page shell; **preserve every wired behavior** the current page already has (conflicts, per-section edit, approve-blocked-on-conflicts, export, Ask chat). This is a layout change plus a few new wires — not a rebuild.

### New shell (`NoteReviewClient.tsx`)
- **Note document (center):** a single continuous document, not N bordered cards. Sections are typography + hairline separators. Claims render **format-neutral** — the renderer shows `claim.text` on its own line with no imposed bullet dots; whatever shape the prompt produced is what shows. Empty section → the existing "Not captured" treatment. Reuse `NoteSectionCard`'s edit/conflict logic via a chrome-less `variant="document"` (restyle, don't rewrite).
- **Toolbar (top of the document):** template `<select>`, language EN/FR toggle, Edit (per-section, existing), Print (`window.print()`), Export DOCX (existing), Copy.
- **Action rail (right):** the primary action — Approve & sign (existing `approveAll`, still blocked while conflicts unresolved) + Copy to EHR + a one-line state caption. Replaces the bottom `ActionBar`.
- **Ask bar (under the document):** existing `NoteAssistChat`, still gated on `note_review_chat_enabled`.
- The approval-gated add-on cards (Orders / PatientSummary / Coding / EMR / PreviewVsFinal) stay rendered below, unchanged — they only appear post-approval, so they don't touch the day-1 note.

### New wires
- **Template switch** → `regenerateNote({ template_key })`. Options list only templates that exist (specialty defaults + the clinician's own custom templates via `getMyPreferredTemplates` / `listMyCustomTemplates`). No SOAP option until loop-2 seeds it; no Consultation letter (no backend).
- **Language EN/FR** → `regenerateNote({ output_language })`. **Requires updating the stale `regenerateNote` client** (`web/lib/api.ts:479`) to send `output_language` and to handle loop-1's **409 `would_discard`**: on 409, show a plain confirm ("Regenerating drops N video/edit items that can't be rebuilt — continue?"), then resend with `confirm_discard: true`. Web-only change.
- **Copy to EHR** → assemble the note text client-side from `detail.note.sections[].claims[].text` and `navigator.clipboard.writeText`, reusing the `PatientSummaryCard.tsx:120` copy pattern. **Not gated** (Uzziel: no hard gate on copy). Toolbar Copy and rail Copy share one handler. A `TODO(loop-3)` points at swapping this for `GET /notes/{id}/text` when it lands, so web and DOCX/iOS converge on one renderer.

### Format-neutral rendering — the one real content change
The current `NoteSectionCard` renders each section as a bordered card. The document variant drops the card chrome (hairline separators, heading typography) and renders each claim as a clean line with **no forced bullet dot**. It takes a `showCitations` prop, hardwired **false** in loop-4 (see deferred) — so day-1 sees a clean note with no chips and no Sources rail.

## Acceptance criteria

- [ ] AC-1: The note renders as one continuous document (no per-section card borders); sections are headings + hairlines — visual check + `NoteReviewPage.spec` asserts no `NoteSectionCard` card-chrome class in document mode.
- [ ] AC-2: An empty section shows "Not captured" (preserved) — existing spec stays green.
- [ ] AC-3: Copy assembles the full note text and writes it to the clipboard; **not** blocked by conflicts or approval state — `NoteReviewPage.spec::copy_writes_full_note`.
- [ ] AC-4: Template switch calls `regenerateNote({template_key})` then re-fetches — `::template_switch_regenerates`.
- [ ] AC-5: Language toggle calls `regenerateNote({output_language})`; on a 409 `would_discard`, a confirm appears and a second call carries `confirm_discard:true` — `::language_switch_handles_409`.
- [ ] AC-6: Conflicts are preserved — amber, inline, `resolveConflict` wired, and Approve stays disabled while `conflict_state.has_unresolved` — existing conflict specs stay green.
- [ ] AC-7: Ask chat still gates on `note_review_chat_enabled` (hidden when off) — existing spec stays green.
- [ ] AC-8: `showCitations={false}` → no citation chips, no Sources rail rendered — `::citations_hidden_by_default`.
- [ ] AC-9: `npm run lint` clean · `npx vitest run` green · `npm run build` (static export) succeeds.
- [ ] AC-10: Zero backend, zero iOS — `git diff --stat main...HEAD -- backend/ ios/` empty.

## DRY / SOLID check

- **Reused:** `NoteSectionCard` (edit + conflict logic, restyled not rewritten), `NoteAssistChat`, `CompletenessRing`, the `PatientSummaryCard` clipboard pattern, `regenerateNote`, `resolveConflict`, `approveAll`, `exportNote`, `editNote`, `getNoteDetail`.
- **New:** the shell layout, a template `<select>`, a language toggle, one Copy handler, the note→text client assembler. Kept small.
- **iOS UI:** n/a (web only).

## Out of scope — deferred to loop-4b, named so they aren't lost

- **Citation visibility** — the super-user gate Uzziel described (flag + role/workspace/per-user targeting + a settings toggle). loop-4 hardwires `showCitations=false`; loop-4b builds the gate and flips it on.
- **The collapsible Sources rail + per-claim citation chips + click-to-source.** Bundles with citation visibility. (This removes the always-on transcript column from the main screen now — exactly Marie's ask — and brings it back collapsed-behind-the-flag in loop-4b.)
- **Encounter audio replay** (`EncounterAudioCard`, #338 — writes an `EVIDENCE_REPLAYED` audit row per play). Removed from the default screen with the transcript; it's a source-playback surface, so it returns in the Sources rail footer in loop-4b (where the approved design placed it). Backend endpoint untouched.
- **Detail level** (Brief/Standard/Detailed) — no `NoteClaim` field; needs backend.
- **Consultation letter** — downstream document transform; doesn't exist.
- **SOAP in the template dropdown** — appears once loop-2 seeds `soap.json`.
- **Cross-clinician "Patient notes" sidebar + "continue this note"** — behind `cross_clinician_chart_enabled`; its own feature.
- **Copy → `GET /notes/{id}/text`** — loop-3; Copy uses client assembly until then (`TODO(loop-3)`).
- **Free-text whole-note editor** — keep per-section `editNote` (the design's version drops citations on save).

## Test plan (executable)

1. `cd web && npm run lint`
2. `cd web && npx vitest run` — update `web/tests/NoteReviewPage.spec.tsx`; add copy / template / language-409 / citations-hidden cases.
3. `cd web && npm run build` — static export must succeed (the `<a href>` vs `<Link>` gotcha).
4. Manual: `npm run dev` → open a note → switch template (regenerates) → toggle FR (regenerates) → Copy → paste shows the full note → conflict note keeps Approve disabled + amber.
5. `git diff --stat main...HEAD -- backend/ ios/` → empty.

## Security implications

- **PHI:** Copy puts the note on the clipboard — that is the intended action (physician → EHR), same as the existing DOCX export and `PatientSummaryCard` copy. No PHI to logs. The client-assembled text is the same claim text already rendered on screen.
- **Descriptive mode:** no AI prompt changed. Template/language switches call the existing `regenerate` path, which owns the prompt.
- **Conflicts:** the CLAUDE.md "100% resolved before approval" gate is preserved exactly — Approve stays disabled on `has_unresolved`, `resolveConflict` unchanged. Copy is deliberately not gated (product decision), and Copy is not approval — the note isn't signed by copying.
- **No new endpoints, no new secrets, no audit changes.**

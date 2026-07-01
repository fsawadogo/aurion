# Plan — scribe-0 (#620): de-conflict export disclaimers

## Task
Stop exports from stamping "descriptive record … contains no diagnostic or
interpretive conclusions" — a **false statement** on a grounded, synthesized
note (Grounded Synthesis is live behind the flag). The operational half
(un-publishing the descriptive note-gen prompt) is already done by the CPO.

## Why
`export/service.py` (DOCX + text) and iOS `NoteDocumentBuilder.swift` (DOCX)
hardcode a descriptive-mode disclaimer. Once `grounded_synthesis_enabled` is on,
a synthesized note is exported mislabelled — a regulatory/labelling gap flagged
for GS-9. Context: `docs/eval/grounded-synthesis-lipo360-finding.md`, `memory/grounded-scribe-gap-map.md`.

## Approach
- **backend `export/service.py`**: extract `_export_footer()` — **mode-aware**.
  Flag OFF returns the exact prior wording (byte-identical); flag ON returns an
  AI-generated/source-grounded/review-required label. Used by both DOCX + text.
- **iOS `NoteDocumentBuilder.swift`**: iOS does NOT read the grounded flag, so
  make the disclaimer **mode-neutral** — drop the false "descriptive record / no
  diagnostic or interpretive conclusions" claim; use "AI-generated clinical note
  — clinician review required," true in both modes.

## Acceptance criteria
- [ ] AC-1: flag OFF → backend footer byte-identical to today.
- [ ] AC-2: flag ON → backend footer contains no "descriptive record" / "no diagnostic or interpretive" claim; states source-grounded + review-required.
- [ ] AC-3: iOS export disclaimer no longer claims "no diagnostic or interpretive conclusions" (mode-neutral).

## DRY / SOLID check
- One `_export_footer()` shared by both backend export paths (was two copies of the literal). iOS is presentation-only.

## Out of scope
- iOS mode-AWARE labelling (needs the backend to send the grounded flag to the app) — follow-up. Render layout / selectable-text / citation-hiding → #625 (scribe-5).

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/test_export_footer.py -q`
2. iOS build verified by CI (no Xcode locally).

## Security implications
- Labelling accuracy only; flag-gated (OFF byte-identical). No PHI, no AI call, no consent/masking/audit path touched. Directly serves the GS-9 export-labelling requirement.

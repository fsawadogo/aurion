# Template engine × iOS — status + handoff for Faïçal

**From:** Uzziel (+ Claude) · 2026-07-29 · companion to `docs/eval/template-engine-eval-lipo360.md`

## TL;DR — nothing blocks iOS today

The template engine is entirely server-side. iOS already sends the two fields that drive it —
`consultation_type` + `context_id` on session create (`APIClient.swift:84-91`) — and the backend resolves the
template (context pin → visit-type default → org default → specialty). The note screen renders sections
generically, so custom-template notes (e.g. the 15-section lipo consult) display correctly on device with no
iOS change. The engine flag is currently ON in dev (see governance note below), so iOS sessions are already
getting template-shaped Stage-1 notes and template-aimed Stage-2 captions.

## What we verified live (2026-07-29, dev)

Full run through the upload path (same server pipeline as iOS): visit type + context → server resolved
`plastic_lipo_consult_v2` with no manual template pick → note rendered all 15 sections in order, following
each section's guidance → signed. Full receipt: `docs/eval/template-engine-eval-lipo360.md`.

## Your queue (none urgent, in priority order)

1. **TE-5b — export S/O/A/P grouping** (`ios/Aurion/Aurion/Export/NoteDocumentBuilder.swift:271-279`).
   The S/O/A/P mapping hardcodes built-in section ids; custom-template ids (`medications_supplements`,
   `risks_benefits`, `post_op_expectations`, `next_steps`, `vitals_weight_height_bmi`, …) fall outside it, so
   on-device DOCX export of a custom-template note groups sections crudely. Planned fix rides on TE-5
   (backend template-bound output shape — not built yet); worth checking what the current fallback does with
   unmatched ids in the meantime.
2. **Section-status badges on the note screen.** Backend bug (being fixed server-side, chip task_1694abe3):
   a section can arrive `pending_video` or `not_captured` while holding transcript claims — on our run the
   fully narrated Physical exam displayed "Pending visual" (v1) / "Not captured" (v2). Once the backend
   coerces statuses, iOS should need nothing — but please sanity-check how SessionNoteView renders these
   states on a signed note.
3. **loop-1b — append-recording loss gate** (previously routed to you): `ResumeRecordingSheet.swift` path can
   regenerate Stage 1 over a Stage-2 note. Dark in prod (`note_options_enabled`… now ON in dev config —
   worth re-checking exposure).
4. **FYI — version divergence** (chip task_5d2cc08b): after approval raced Stage 2, the clinician surface
   shows signed v1 while a stage-2 v2 exists. If iOS export reads "latest" vs "signed" it inherits the same
   question — flag which one `NoteDocumentBuilder` pulls.
5. **FYI — masking audit** (chip task_5a2d403b): the web upload path ran vision on frames the eval header
   flags as Unmasked. Your on-device masking contract is the reference implementation; expect questions
   about what the server-side path should mirror.

## Governance note (Uzziel's call, you should know)

`template_engine_enabled` AND `grounded_synthesis_enabled` were found ON in the dev config with an EMPTY
change history — set by an earlier unaudited config push, not the audited Feature Flags page. GS is on
without its #551/GS-9 sign-off (its runtime slices appear inert on the paths we exercised). Being resolved
via chip task_ec25e4de; posture decision pending.

## Questions for you

1. TE-5b timing: once TE-5 lands the section enum, is the export mapping a template-driven lookup on your
   side, or do you want the backend to ship the S/O/A/P grouping per template?
2. Does anything else on iOS assume the 8 built-in template keys (backlog mentions the Siri `AppEnum`)?
   The web has retired them from clinician pickers (TE-4e/4g/4h); iOS parity eventually follows.
3. Which note version does iOS export read — latest or signed?

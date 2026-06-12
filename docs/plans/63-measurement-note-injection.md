# Plan — #63 measurement note-injection slice (backend)

Third #63 slice. Persistence (#433) gave a confirmed measurement a home and
an ingest endpoint. This slice routes that confirmed measurement *into the
note* as a traceable claim — the same `NoteClaim` pattern the vision/screen
pipelines use (`merge_visual_citations`).

Still ships **dark** — injection only runs inside the ingest path, which is
gated by `feature_flags.measurement_enabled`.

## Scope

- `modules/measurement/note_injection.py` (pure, no I/O) —
  - `_SECTION_ROUTES`: kind → ordered target section ids. Route into the
    first section the active note defines (wound → `wound_assessment` then
    `physical_exam`; rom_angle → `functional_assessment` then
    `physical_exam`). No matching section → left un-injected.
  - `format_measurement_text`: descriptive-mode claim text ("…approximately
    42 mm (iPhone AR, LiDAR, physician-confirmed).").
  - `inject_into_note(note, citation)`: append the claim in place; no-op when
    not physician-confirmed, already injected (idempotent on
    `measurement_id`), or no routed section. Marks an empty section populated.
- `api/v1/me_measurements.py` — after the `MEASUREMENT_REVIEWED` audit on a
  confirmed create, load the latest note and, if injection changed it, write
  a new note version (`create_note_version`, trigger `measurement_injection`).

## Out of scope

- **iOS AR instrument + NoteReview confirm card** — needs a device.
- **Re-injection when the note appears *after* confirm** — if Stage 1 hasn't
  delivered a note at confirm-time, the measurement is persisted + listable
  but not injected. In the real flow the physician confirms *during* note
  review, so the note exists; a backfill pass is a later slice if needed.
- **Edit / suppress flows** (`MEASUREMENT_EDITED` / `_SUPPRESSED` events exist
  but aren't wired) — future.
- **Accuracy-characterization study + legal export-label review** — gate any
  patient use; not a code slice.

## Non-negotiables honoured

- Descriptive mode: claim text reports the number "approximately" with method
  + provenance — no trend, interpretation, or diagnosis (asserted by a
  negative-keyword test).
- `certified_measurement` stays structurally False (carried on the citation).
- Audit append-only; note versions are immutable + never deleted.
- No new AI call. Injection is deterministic string assembly.
- Module isolation: `note_injection` imports only `core.types`; the
  cross-module `note_gen` call lives at the API layer, mirroring
  `vision.py`/`screen.py`.

## Test plan

`pytest tests/unit/ -q` · `ruff check`. New:
`test_measurement_note_injection.py` (routing across specialties, claim text +
descriptive-mode negative-keyword guard, confirmed-gate, idempotency, no-op);
plus endpoint-wiring cases in `test_measurement_persistence.py` (injects +
versions when a note with a target section exists; skips version when no note
/ no target section).

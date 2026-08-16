# VIS-09 — Collapse duplicate visual captions before the merge

## Task

VIS-09 — mark visual-vs-visual duplicate captions `REPEATS` so the merge's
existing discard path drops them, instead of writing one claim per frame.

## Why

Measured on session `30cccd75` (bb7dabb1, the 180s exam + X-ray clip, Anthropic
both stages, MSK knee template) against Dr. Marie Gdalevitch's answer key:

- Stage 1 (audio only): **33 claims**. Clean, close to Marie's shape.
- Stage 2 (vision merged): **~85 further visual claims**, of which Imaging
  Review alone carries roughly **65 claims describing ~5 distinct things** —
  ~27 of the bilateral AP standing view, ~19 of the lateral, ~8 of the
  sunrise/Merchant, plus misrouted exam frames.

Marie documents the same imaging in **three lines**, one per view. The note is
not wrong so much as unreadable: frames are cadence-sampled every 5s
(`video_import_cadence_seconds: 5`), the surgeon holds one X-ray on screen for
two minutes, and **every frame becomes its own claim**.

The handoff recorded the identical pattern on session `f3a8e35d` — 75 claims /
16 distinct observations / 7,303 words — so this reproduces across sessions,
clips and specialties.

CLAUDE.md §Phase 4 specifies `REPEATS → discard`. This makes that real.

## Approach

**Root cause.** The discard path already exists and is dead code:

1. `providers/vision/shared.py:160` — `build_frame_caption` hardcodes
   `integration_status="ENRICHES"` on every caption.
2. `vision/service.py:classify_conflicts` is a stub: it flips `conflict_flag`
   only when the status is *already* `CONFLICTS`, counts, logs, returns
   unchanged. Its docstring says it "trusts the provider's classification" —
   but the provider never classifies.
3. `vision/service.py:1115` — the merge filters
   `integration_status != "REPEATS"`, and **nothing ever produces a REPEATS**.

There is also a conceptual gap: `REPEATS` was conceived as "does this caption
repeat the *audio*?". Nothing asks "does this caption repeat the *previous
caption*?" — which is the redundancy we actually have.

**Change.** Implement the classification in `classify_conflicts`, keyed on
redundancy between sibling captions:

- Group captions by the section they route to (reusing
  `_section_for_caption_text`, the TE-4 router — no second routing rule).
- Within a group, score similarity on **discriminative** tokens only. Terms
  occurring in a majority of the run's captions ("monitor", "displays",
  "visible", "no", "appears") carry no information and are dropped before
  comparison; what remains distinguishes ("lateral", "sunrise", "Merchant",
  "UPRIGHT", "patella", "prone").
- Above a threshold, keep one representative — highest confidence, then most
  specific — and mark the rest `REPEATS`.
- A cluster of one always survives.

**Files**
- `backend/app/modules/vision/service.py` — implement `classify_conflicts`;
  add a private `_dedupe_captions` helper beside it.
- `backend/tests/unit/test_vis09_visual_dedup.py` — new.

**No** schema change, **no** merge change, **no** provider change. TE-4's
routing and the caption voice are untouched.

## Acceptance criteria

- [ ] AC-1: given N captions whose discriminative content matches, exactly one
      survives with `integration_status == "ENRICHES"` and the rest are
      `REPEATS` — verified by
      `test_vis09_visual_dedup.py::test_duplicate_captions_collapse_to_one`.
- [ ] AC-2: captions describing genuinely different views (AP standing vs
      lateral vs sunrise/Merchant) are NOT collapsed — verified by
      `test_distinct_imaging_views_survive_dedup`.
- [ ] AC-3: a single caption is never dropped, including every phrase from
      the TE-4 no-deletion guard ("Bone is not visible at the base of the
      ulcer.", etc.) — verified by
      `test_lone_caption_never_dropped` and `test_te4_negative_findings_survive`.
- [ ] AC-4: dedup keys on sibling redundancy, NOT on wording — a caption is
      only ever dropped when another caption in the same section carries the
      same discriminative content — verified by
      `test_no_wording_based_deletion`.
- [ ] AC-5: every dropped caption is logged with its representative's
      `frame_id`, and no PHI is logged — verified by
      `test_dropped_captions_are_logged_without_phi` (caplog assertion).
- [ ] AC-6: replaying the 65 real Imaging Review captions from session
      `30cccd75` yields ≤ 10 surviving claims while retaining all three
      distinct X-ray views — verified by
      `test_real_session_30cccd75_collapses` (fixture from the eval harness).
- [ ] AC-7: `tests/unit` stays green (2,212 passing at branch point) —
      verified by `cd backend && python -m pytest tests/unit -q`.

## DRY / SOLID check

- **Existing helpers to reuse**: `_section_for_caption_text` (TE-4's router —
  the dedup groups by the SAME routing decision the merge will use, so the two
  can never disagree); `integration_status` + the existing `REPEATS` filter at
  `service.py:1115`; `logger` already configured on the module.
- **New helper introduced?**: yes — `_dedupe_captions`. Justified: it is the
  single implementation of a rule the merge, the Grounded Lab and fusion all
  consume through `classify_conflicts`; putting it anywhere else would create
  a second copy for the lab path (which already diverged once, see #764).
- **SRP**: `_dedupe_captions` decides redundancy only. It does not route, does
  not rewrite text, does not touch the note.
- **OCP/LSP**: no provider branching; operates on `FrameCaption` after the
  provider boundary, so all three providers dedupe identically.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a, backend only.

## Out of scope

- **Clip extraction for motion-defined manoeuvres** (Lachman / McMurray /
  patellar tests). Measured separately: vision named **0 of 7** of Marie's
  manoeuvres because stills cannot resolve a movement. That is VIS-10.
- **Misrouted exam frames landing in Imaging Review** (~10 in this run,
  including one reading "No radiographic imaging is visible in this frame").
  Routing bug, separate change.
- **The reproduced scar fabrication** ("a well-healed linear surgical scar…"
  on a patient with no knee surgery). Separate.
- **PHI read off screens into claims.** Separate, and severity depends on
  whether the on-screen study is real — deferred pending that answer.
- Rewriting or summarising caption text. This change only ever REMOVES
  whole captions, never edits one — so it cannot introduce content.

## Test plan (executable)

1. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_vis09_visual_dedup.py -v`
2. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_te4_template_formatted_merge.py -v`
   (the no-deletion guard must stay green)
3. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit -q`
4. Replay in the eval harness: capture session `30cccd75` before/after and
   compare Imaging Review claim counts in `eval/knee-harness/index.html`.

## Security implications

- **PHI**: none added. The dedup reads caption text already in memory and
  logs only `frame_id` values plus counts — never caption text, which may
  describe patient anatomy. Asserted by AC-5.
- **Audit log**: unchanged. No new events.
- **Secrets / AI prompts / consent gate**: untouched.
- **Descriptive mode**: unaffected — removing a redundant claim cannot make
  the note less grounded. The surviving representative keeps its own
  `source_id = frame_id`, so citation traceability is preserved.
- **Risk**: dropping claims changes the `completeness_score` denominator.
  Mitigated by AC-2 (distinct findings survive) and AC-3 (lone captions
  survive); the score should rise in precision, not fall in coverage.

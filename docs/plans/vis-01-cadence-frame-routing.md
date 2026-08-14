# Plan — VIS-01/02/03: cadence frames routed by content, not by concurrent speech

## Task

VIS-01 (#743) + VIS-02 (#744) + VIS-03 (#745) — stop discarding ~99% of
captured frames because they are captioned against a section chosen from
what was being *said* rather than what is *shown*.

Shipped as ONE change: VIS-01 is inert alone, and VIS-02 without VIS-03
would file un-aimed captions under whatever the concurrent speech belonged
to — a wrong-section claim in a clinical note is worse than an empty
section.

## Why

Measured on dev, session `01ce3561` (bunion clip):

```
Captioning complete: total=182 captioned=2 discarded=180 failed=0
Stage 2 complete:    frames=182 clips=0 enriches=0 conflicts=0
```

The model read the frames correctly — its own discard reasons say so
("a computer screen displaying an X-ray"). `frame_85000` extracted locally
and run through the real `mask_frame` shows a crisp, fully legible foot
X-ray with `text_regions_redacted=0`, so masking is not the cause.

The cause is a self-defeating interaction:

1. `_find_anchor_segment` picks the transcript segment closest in TIME.
2. `_find_target_section` tier 1 returns the section citing that segment.
3. `_section_focus_block` then instructs the model: *"If nothing relevant
   to this section is visible, say so AND report confidence low."*

Cadence sampling exists to catch visuals the audio does NOT mention — and
is then judged by what the audio was saying. Every cadence frame whose
content diverges from concurrent speech is guaranteed to be discarded.

CLAUDE.md §Pipeline Architecture: *"Video is the flesh — frames at trigger
timestamps → vision provider → citation objects."* Today the flesh is
captured, described, and thrown away.

## Approach

Files:

- `backend/app/modules/vision/service.py`
  - NEW `frame_provenance(trigger_segments, timestamp_ms) -> str` (VIS-01):
    pure; `"trigger"` iff the timestamp falls inside some trigger segment's
    window, honouring `get_frame_window_ms(seg.trigger_type)` — the SAME
    arithmetic `_extract_and_mask_frames` used to choose those windows.
  - `caption_visual_evidence` (VIS-02): pass `template=None` into
    `_section_focus_block` for cadence evidence, so it returns `None` and
    the frame is captioned on the base `VISION_SYSTEM_PROMPT` with no
    forced low-confidence instruction.
  - `merge_visual_citations` (VIS-03): for cadence captions, resolve the
    target section from the CAPTION text before falling back to the anchor
    router.
  - NEW `_section_for_caption_text(template, note, text)`: matches caption
    text against each template section's `visual_trigger_keywords`,
    restricted to sections that are visual sinks. Reuses the existing
    keyword-matching shape from `_template_section_for_anchor_text` rather
    than inventing a second matcher (DRY).

No schema change, no migration, no iOS change, no storage-contract change.

Subagents: none — this is a surgical change to one module and the workflow's
`@backend-builder` delegation would add context churn without adding
information. `@compliance-checker` equivalent runs as the security greps in
§Security implications below.

## Acceptance criteria

- [ ] **AC-1**: `frame_provenance` returns `"trigger"` for a timestamp inside
  a trigger window and `"cadence"` outside every window, honouring the
  configured frame window —
  `pytest tests/unit/test_cadence_frame_routing.py -k provenance`
- [ ] **AC-2**: a cadence point that lands INSIDE a trigger window classifies
  as `"trigger"` (correct by definition) —
  `pytest tests/unit/test_cadence_frame_routing.py -k inside_window`
- [ ] **AC-3**: `_section_focus_block` returns `None` for cadence evidence and
  the unchanged block for trigger evidence —
  `pytest tests/unit/test_cadence_frame_routing.py -k focus_block`
- [ ] **AC-4**: a cadence caption naming an imaging study routes to
  `imaging_review` even when the audio anchor's claim sits in `hpi` —
  `pytest tests/unit/test_cadence_frame_routing.py -k routes_by_content`
- [ ] **AC-5**: content routing never selects a non-visual section (`plan`,
  `medications`, …) —
  `pytest tests/unit/test_cadence_frame_routing.py -k never_non_visual`
- [ ] **AC-6**: trigger-frame captioning and routing are unchanged —
  `pytest tests/unit/test_cadence_frame_routing.py -k trigger_unchanged`
- [ ] **AC-7**: no regression — `pytest tests/unit -q` fully green
- [ ] **AC-8**: stack boots — `docker compose up -d && curl -fs localhost:8080/health`
  returns 200

## DRY / SOLID check

- **Existing helpers to reuse**: `get_frame_window_ms` (window sizing —
  never hardcode, per CLAUDE.md), `_template_section_for_anchor_text`
  (keyword-matching shape), `_LEGACY_VISUAL_SECTIONS` (the visual-sink
  allow-list), `note.get_section`, `_find_target_section` (kept as the
  fallback so one router still owns placement).
- **New helper introduced?**: two, both justified by crossing a boundary
  rather than duplicating a pattern. `frame_provenance` is a new *concept*
  (evidence origin) with no existing expression anywhere in the codebase.
  `_section_for_caption_text` is a sibling of `_template_section_for_anchor_text`
  — same matching mechanics, different input (caption vs transcript). They
  are deliberately NOT merged: collapsing them would take a `source: str`
  flag argument, which is the control-coupling smell SRP exists to prevent,
  and the two have genuinely different fallback semantics.
- **OCP**: routing extends via the template's own declared sections; no
  `if section_id == ...` branching added.
- **DIP**: window sizing still reads AppConfig through `get_frame_window_ms`.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a, no iOS files.

## Out of scope

- VIS-04 (#746) tier-3 note-order fallback — independent, separate PR.
- VIS-05 (#747) unbounded `_find_anchor_segment` — independent, separate PR.
- VIS-06 (#748) surfacing capture/discard counts — independent, separate PR.
- Flipping `keep_low_confidence_visual_findings`. Deliberately left OFF so
  the discard rate stays an honest success metric for this change.
- Changing which sections count as visual sinks per template.
- Clip evidence (`MaskedClip`) routing — frames only.

## Test plan (executable)

1. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit/test_cadence_frame_routing.py -v`
2. `cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit -q` → all green
3. `cd backend && ./.venv/Scripts/python.exe -m ruff check app/modules/vision/service.py tests/unit/test_cadence_frame_routing.py`
4. `docker compose up -d && curl -fs localhost:8080/health` → 200
5. Post-merge on dev: re-run the SAME bunion clip and compare against the
   recorded baseline `frames=182 captioned=2 discarded=180 enriches=0`.

## Security implications

- **PHI**: none added. Caption text is already handled evidence; the new
  routing reads it in-process and logs only section ids, never caption or
  transcript text. Existing `_screened_fragment` gate on template text is
  untouched.
- **Descriptive mode**: this REMOVES a prompt block for cadence frames; it
  adds no prompt text. Cadence frames fall back to `VISION_SYSTEM_PROMPT`,
  which is the CLAUDE.md-sanctioned descriptive prompt verbatim. The
  removed instruction is the "report low confidence if irrelevant" line —
  dropping it cannot weaken the descriptive boundary, which lives in the
  system prompt the caller keeps first and intact.
- **Grounding**: a caption still becomes a `NoteClaim` cited to its frame.
  Routing changes WHICH section receives it, never whether it is cited.
- **Audit log**: untouched.
- **Secrets / consent gate / masking**: untouched.
- **Human-review flag**: VIS-03 lets the model influence section placement.
  Bounded to declared visual sections, but it is a grounding-adjacent
  decision and the PR asks for a human tick before merge.

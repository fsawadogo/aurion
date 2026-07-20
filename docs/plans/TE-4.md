# Plan — TE-4

## Task

TE-4 — replace the verbatim caption paste in `merge_visual_citations`: route by the **template's** sections and construct the claim text, instead of pasting `caption.visual_description` into a section chosen from a hardcoded list.

## Why

TE-3 aimed the *capture*. The *merge* is still `text=caption.visual_description` verbatim (`vision/service.py:900`) into a section picked from a hardcoded id tuple (`:1130`). So a frame's contribution to the note is still whatever prose the model happened to emit.

**And TE-3 made one case actively worse.** Its prompt instructs the model: *"If nothing relevant is visible, say so — never infer, diagnose, or fill a gap."* That is the right instruction — but today's merge then pastes *"Nothing relevant to the wound assessment is visible in this frame"* into the patient's note as a claim. TE-3 **guarantees** these captions now exist. Left alone, the root fix for clutter adds a new kind of clutter.

Satisfies backlog `Cohort 7 · TE-4`, and carries the defect recorded against it during TE-3's review.

## The recorded defect this slice must close

`_find_target_section` tier 3 makes **prediction and placement disagree**. Two independent causes:

- `merge_visual_citations` flips its target `pending_video → populated` *as it goes* (`:906-907`), so tier 3 answers differently for the second caption than it did at capture time;
- REPEATS captions are dropped *between* the two calls (`:888`), shifting which caption consumes which section.

Consequence on a custom template whose ids fall outside the tier-2 tuple — i.e. **exactly the templates this epic exists for** — two frames are captured under one section's guidance and filed under two.

**Root fix: route every caption against the pristine note, before any mutation.** Capture-time prediction runs on the same `Note` object (`run_stage2_vision` loads it once and captioning does not mutate it), so routing all captions up-front makes placement *identical* to prediction by construction, not by coincidence. No new state, no field on `FrameCaption`.

## Approach

One gated branch. `template is None` (engine off) keeps today's path exactly.

1. **Route-then-apply.** Compute `[(caption, section)]` for all non-REPEATS captions from the unmutated note, then apply. Closes the divergence.
2. **Template-driven tier 2.** Replace the hardcoded `("imaging_review", "physical_exam", "wound_assessment", "functional_assessment")` with the template's own sections — a section is visual-by-nature when the template gives it `visual_trigger_keywords` or `measurement_output_expected`. Both fields already exist and `visual_trigger_keywords` is unused at this stage. No template → the hardcoded tuple, unchanged.
3. **Drop no-finding captions.** A caption that reports nothing relevant is not evidence; it is the absence of evidence. Dropped before it becomes a claim, and counted so the audit row still reflects what was processed.
4. **Format the claim.** Strip the model's image-meta preamble (*"The image shows…"*, *"In this frame, …"*, *"The photo depicts…"*) so the claim reads as a clinical observation rather than an image caption, normalise whitespace, ensure terminal punctuation.
5. **One construction site.** `_build_visual_claim(caption, spec)` becomes the single place a visual `NoteClaim` is constructed — the D3 requirement, so flipping `grounded_synthesis_enabled` later upgrades the frames path with no rearchitecture.

**Deterministic, not another model call.** The formatter is pure string work. Re-generating claim text with an LLM would put a second, unscreened generation between the caption and the chart — new grounding risk for cosmetic gain.

**Honest scope note.** The template's real contribution at merge is **routing**. Steps 3 and 4 are deterministic de-cluttering that would help regardless. Calling the whole slice "template-formatted" oversells step 4; the plan says what each part actually does.

## Acceptance criteria

- [ ] **AC-1:** `claim.text != caption.visual_description` while `claim.source_id == frame_id` and `source_type == "visual"` — traceability unchanged
- [ ] **AC-2:** flag OFF → merged note byte-identical to today, asserted against the pre-change behaviour
- [ ] **AC-3:** a no-finding caption produces **no claim**, and does not flip a section to `populated`
- [ ] **AC-4:** image-meta preamble is stripped; the clinical content is preserved verbatim after it
- [ ] **AC-5:** routing uses the template's sections; a custom template's own visual section wins over the hardcoded tuple
- [ ] **AC-6:** **prediction == placement** for every caption, including 2+ tier-3 captions on a custom template — the recorded defect, now a passing test where it was a pinned failure
- [ ] **AC-7:** CONFLICTS still produce a `conflict_`-prefixed visual claim, so `is_unresolved_conflict_claim` and the approval gate are unaffected
- [ ] **AC-8:** full `tests/unit/` green; `ruff` clean

## DRY / SOLID check

- **Existing helpers reused:** `_find_target_section` (extended, not duplicated), `note.get_section`, `_screened_fragment` if any template text reaches output. Precedents followed: `measurement/note_injection.py` (`format_measurement_text` + `select_target_section` preference router) and `screen.py:_value_to_claim_text` — both are "structured input → deterministic descriptive claim", which is exactly this shape.
- **New helpers:** `_build_visual_claim` (single construction site) and `_is_no_finding_caption`.
- **SRP:** routing and text construction stay separate functions; TE-5 changes neither.
- **iOS UI task?** No. Claim rendering is generic (`ForEach(note.sections)`), and `source_type`/`source_id` are unchanged, so citation chips and tap-to-source keep working.

## Out of scope

- **Multi-source fusion** (one claim citing a frame *and* a transcript segment) — grounded synthesis, needs GS-9. Step 5 exists to make it a later drop-in.
- **Re-generating caption text with a model** — see above.
- **TE-5's output schema** — different slice.
- **The eval receipt.** TE-4 makes it *meaningful* (TE-3 alone still pasted verbatim), but running it is its own task.

## Test plan (executable)

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_te4_template_formatted_merge.py -v`
2. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ -q` → full suite green
3. `cd backend && .venv/Scripts/python.exe -m ruff check app/ tests/` → clean
4. Mutation-test each fix: revert it, confirm its test fails
5. `docker compose ... up -d && curl -fs localhost:8080/health` → 200
6. `git diff --stat main...HEAD -- ios/ web/` → empty

## Security implications

- **Descriptive mode:** the formatter only *removes* text (preamble, whitespace) and never adds clinical content. It cannot introduce an inference, because it cannot introduce words.
- **Traceability:** `source_type="visual"` and `source_id=frame_id` are preserved on every claim — the ≥95% citation-traceability target is unaffected. Dropped no-finding captions produce no claim at all, so they cannot be untraceable.
- **The conflict gate is contract, not text.** `is_unresolved_conflict_claim` keys off `source_type == "visual"` and `id.startswith("conflict_")`, not the claim's wording — verified. TE-4 keeps both, so CONFLICTS still hard-block approval.
- **No PHI in logs:** drop/route decisions log section ids and frame ids only, never caption text (a caption describes a patient).
- **Flag:** OFF is byte-identical, asserted (AC-2).

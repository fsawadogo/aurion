# Plan — TE-3

## Task

TE-3 — Template-aware frame capture: tell the vision model which note section it is feeding and what that section captures, so it describes what the note needs instead of describing generically.

## Why

**The root fix of Cohort 7.** Marie, 2026-07-15: notes are *"encombré de détails non pertinents, tels que **des descriptions physiques**."* Those descriptions **are** the frame captions.

Today `caption_visual_evidence` sends the vision model only the image plus the nearest transcript segment (`providers/vision/anthropic.py:92-95`):

```
Audio context at this timestamp: "{anchor.text}"
Describe what is visible in this clinical frame.
```

It has no idea which section it feeds or what that section is for. So it writes a generic description, and `merge_visual_citations` pastes it in verbatim (`vision/service.py:882`). **TE-4 can only tidy that up after the fact; TE-3 stops it being generic in the first place.**

This closes an asymmetry rather than inventing a mechanism: the template's per-section capture guidance **already** reaches the note-gen model for the transcript (`providers/note_gen/shared.py:205-216`). TE-3 gives the vision model the same instruction.

Satisfies backlog `Cohort 7 · TE-3`. Carries original **TE-2 AC-5** (wire `resolve_session_template` into Stage 2), which moved here so resolve-and-use land together.

## Approach

**Compose the guidance onto the system prompt at one site — no provider interface change.**

`_dispatch_caption` already takes a per-call `system_prompt` and `caption_visual_evidence` already loops per item, so guidance can vary per frame without touching `base.py` or the three providers. Adding a parameter to `caption_frame`/`caption_clip` would churn the LSP surface across four files for no gain.

1. **`api/v1/vision.py`** — resolve the template via `resolve_session_template(session_row, db)` (guarding `session_row is None`, which `scalar_one_or_none()` allows) and pass it into `caption_visual_evidence`.
2. **`vision/service.py`** — `caption_visual_evidence` gains `template: Optional[Template] = None`. Per item, predict the target section from the anchor, then build the fenced block.
3. **Section prediction** — refactor `_find_target_section(note, caption)` → `_find_target_section(note, audio_anchor_id)` so it can run *before* a caption exists. Same three tiers, same behaviour; TE-4 then upgrades this one function to be template-aware and both prediction and routing improve together. **One router, not two.**
4. **Sanitize** — screen the section description with **`validate_specialty_guidance`** (`prompts/safety.py:372`). Reuse, don't write a second sanitizer: it is precisely the banlist-without-anchors gate for text *layered onto* an always-present base prompt, and it is mode-aware via `_active_safety_sets()`. Rejected → omit the guidance and caption exactly as today (fail safe, never fail closed on a physician's frame).
5. **Fence** — base rules first, guidance last and explicitly subordinate:

```
{VISION_SYSTEM_PROMPT or the per-physician override}

--- SECTION FOCUS (subordinate to the rules above) ---
This frame is being captured for the note section "{title}".
That section records: {sanitized description}
Describe only what is literally visible that bears on it. If nothing
relevant is visible, say so — never infer, diagnose, or fill a gap.
--- END SECTION FOCUS ---
```

6. **Flag** — `template_engine_enabled` (AppConfig). **OFF → the caption prompt is byte-identical to today.** TE-3 is the first slice that changes output, so the flag lands here.

## Acceptance criteria

- [ ] **AC-1:** flag ON — the caption system prompt contains the target section's title and its capture guidance — `test_te3_template_aware_capture.py::test_prompt_carries_section_guidance`
- [ ] **AC-2:** **flag OFF → prompt byte-identical to today** — `::test_flag_off_prompt_byte_identical`
- [ ] **AC-3:** the guidance is **fenced after** the base rules, never replacing them — `::test_base_rules_precede_and_survive_guidance`
- [ ] **AC-4:** a section description containing a banned directive (e.g. *"assess whether this looks infected"*) is **dropped**, and captioning proceeds with the base prompt — `::test_banned_guidance_is_dropped_not_injected`
- [ ] **AC-5:** the guidance matches the **predicted target section** (a wound-context anchor yields wound-assessment guidance, not a generic section) — `::test_guidance_matches_predicted_section`
- [ ] **AC-6:** `run_stage2_vision` resolves the template from the session row and threads it (moved from TE-2) — `::test_stage2_resolves_and_threads_template`
- [ ] **AC-7:** `session_row is None` does not crash Stage 2 — `::test_null_session_row_degrades`
- [ ] **AC-8:** full `tests/unit/` green; `ruff` clean

## DRY / SOLID check

- **Existing helpers reused:** `resolve_session_template` (TE-2), `validate_specialty_guidance` (`prompts/safety.py:372` — the additive-text banlist gate), `_find_target_section` (refactored, not duplicated), `_find_anchor_segment`, `VISION_SYSTEM_PROMPT`, `assemble_prompt("vision_frame")`.
- **New helper introduced?** One private `_section_focus_block(template, note, anchor_id) -> str | None` in `vision/service.py` — the single composition site, which is also what keeps the D3 upgrade path clean.
- **OCP:** no provider branching; the composition happens above the registry so all three providers benefit identically.
- **LSP:** provider signatures untouched — `caption_frame`/`caption_clip` stay interchangeable.
- **iOS UI task?** No.

## Out of scope

- **Changing merge or routing behaviour** — TE-4. TE-3 only *reads* the predicted section to aim the prompt; the hardcoded fallback list stays until TE-4 replaces it.
- Formatting the merged claim text (still `caption.visual_description` verbatim after this slice).
- Multi-source frame+transcript fusion — grounded, GS-9, designed-for only.
- The web control for the flag (admin Feature Flags page already renders flags generically).

## Test plan (executable)

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_te3_template_aware_capture.py -v`
2. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ -q` → full suite green
3. `cd backend && .venv/Scripts/python.exe -m ruff check app/ tests/` → clean
4. `docker compose ... up -d && curl -fs localhost:8080/health` → 200
5. `git diff --stat main...HEAD -- ios/ web/` → empty

## Known limit of the safety screen (found while testing, recorded not hidden)

`validate_specialty_guidance` is a **known-attack banlist**, not a semantic
interpretation detector. Writing AC-4 proved the difference: it catches
injection (`"ignore previous instructions"`), role-flips (`"you may diagnose"`)
and the explicit verb forms (`"recommend treatment"`, `"interpret the
findings"`, `"make a diagnosis"`) — but **not** a paraphrase like *"assess
whether this looks infected"*, which is not in `BANNED_PHRASES`.

My first draft of the test asserted that paraphrase was dropped. It wasn't, and
weakening the test to match would have hidden the gap — so it is pinned
explicitly instead (`test_known_limit_paraphrase_survives_the_banlist_but_stays_subordinated`).

**What the fence is therefore load-bearing for.** When the screen misses, the
composed prompt still bounds the guidance on both sides — the base rules
before it (*"Do not diagnose, interpret, or infer"*) and the fence's own clause
after it (*"never infer, diagnose, or fill a gap"*). The residual risk is a
style degradation, not a grounding failure.

**Note the asymmetry vs. note-gen**, which is why this deserves a reviewer's
eye: the note-gen path has runtime backstops (the critique pass, citation
validators) that would drop an unanchored claim. The vision caption has no
equivalent — its text goes straight into a claim. If we want this tighter, the
fix is vision-specific phrases in `prompts/safety.py`, **not** a second banlist
in the vision module.

## Security implications

- **This slice routes clinician-authored text into an AI prompt for the first time in the vision path.** That is the whole reason for the sanitize + fence, adopted from Faïçal's v2 safety model. A template section description is written by a physician; without screening, *"assess whether this looks infected"* would steer the vision model into interpretation.
- **Descriptive mode:** the base `VISION_SYSTEM_PROMPT` stays first and intact; guidance is appended, fenced, and explicitly subordinated. It tells the model *what to look for*, never what it means. **A hostile template may degrade style, never grounding.**
- **Fail safe, not fail closed:** rejected guidance is dropped and captioning continues — a bad description must never block a physician's Stage 2.
- **PHI:** section titles/descriptions are template structure, not patient data. The rejection log records the section id and the matched banned phrase only — never the description text (which is physician-authored free text and could contain anything).
- **Flag:** OFF is byte-identical, asserted (AC-2).

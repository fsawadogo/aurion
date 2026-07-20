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
- [ ] **AC-4:** a section description containing a **banlisted** directive (e.g. *"you may diagnose"*, *"recommend treatment"*) is **dropped**, and captioning proceeds with the base prompt — `::test_banned_guidance_is_dropped_not_injected`. **Corrected:** this AC originally named *"assess whether this looks infected"*, which the shipped code does **not** drop — that paraphrase is not in `BANNED_PHRASES`. The limit is pinned in `::test_known_limit_paraphrase_survives_the_banlist_but_stays_subordinated` and explained below; the AC now states what the code actually guarantees.
- [ ] **AC-4b:** the screen does **not** follow `grounded_synthesis_enabled` — `::test_grounded_mode_does_not_unlock_diagnosis_on_the_vision_path`
- [ ] **AC-5:** the guidance matches the **predicted target section** (a wound-context anchor yields wound-assessment guidance, not a generic section) — `::test_guidance_matches_predicted_section`
- [ ] **AC-6:** `run_stage2_vision` resolves the template from the session row and threads it (moved from TE-2) — `::test_stage2_resolves_and_threads_template`
- [ ] **AC-7:** `session_row is None` does not crash Stage 2 — `::test_null_session_row_degrades`
- [ ] **AC-7b:** a template-resolution failure degrades to template-blind captioning, it does **not** fail Stage 2 — `::test_template_resolution_failure_does_not_fail_stage2`
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
- **The portal toggle for the flag.** My original rationale here was *factually
  wrong* — the admin Feature Flags page does **not** render flags generically;
  `web/app/portal/admin/feature-flags/page.tsx` is a hardcoded `FLAG_GROUPS`
  array, and the flag is also absent from `web/types` and the en/fr messages.
  So `template_engine_enabled` currently needs a direct AppConfig write. Left
  out of this backend slice deliberately, but it **must** land before the
  rollout's "flip it in dev" step — otherwise nobody can turn the engine on.
  Tracked as **TE-3b** (web, S).

## Test plan (executable)

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_te3_template_aware_capture.py -v`
2. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ -q` → full suite green
3. `cd backend && .venv/Scripts/python.exe -m ruff check app/ tests/` → clean
4. `docker compose ... up -d && curl -fs localhost:8080/health` → 200
5. `git diff --stat main...HEAD -- ios/ web/` → empty

## Review findings — two injection vectors the plan missed (fixed)

An adversarial review found that the "sanitize + fence" design as planned was
**not sufficient**, in two ways the banlist could never cover. Both reached a
`NoteClaim` and therefore a patient's chart, and both are fixed.

**1. `title` was interpolated with zero validation.** The plan screened only
`description`. But the title is authored in the same editor, has no
`max_length`, and on the custom-template **update** path skips the create-time
section caps entirely (`_validate_custom_template_fields(..., check_section_caps=False)`).
A title alone could carry `"you may diagnose"` into the prompt — and via admin
shared templates it would reach every clinician in the org. Now flattened **and**
screened, falling back to the section id (a code identifier) when it fails.

**2. The fence delimiter was forgeable.** `validate_specialty_guidance` is a
lowercase substring scan with no newline or delimiter handling. A description
containing a `--- END SECTION FOCUS ---` line followed by a forged
higher-priority block matched **no** banned phrase yet produced a top-level
block structurally indistinguishable from an operator-authored one. **No
banlist entry can fix that class** — it is structural.

Fixed with `_prompt_safe_fragment`: **flatten structure before judging
content.** Whitespace runs (newlines included) collapse to a single space so a
forged block cannot occupy its own line; runs of 2+ hyphens are dropped so the
delimiter is unforgeable; a hard length cap bounds per-frame token cost.
Applied to title and description alike.

Also fixed from the same review: the template was resolved on **every** Stage 2
run regardless of the flag (a dark path must stay dark end-to-end — it added a
DB round-trip and a failure surface); clips were told *"This frame"*, undoing a
deliberate wording choice in the vision prompts; and two ACs cited tests that
did not exist while the AC-3 test asserted on a string the test itself built
rather than the production composition.

## Second review — the first fix was not enough either

Two more independent reviews ran on the fix commit itself, because the review
fixes were substantial new code that had not themselves been reviewed. That
was the right call: **the sanitizer's own fallback reintroduced the exact
structural forge it existed to stop.**

**1. `section.id` was the hole (critical).** The first fix screened the title,
then assigned `section.id` **raw** when it failed, on the strength of a code
comment calling it *"a code identifier"*. It is not. `TemplateSection.id` is a
bare `str` with no charset rule, and `_validate_custom_template_fields(...,
check_section_caps=False)` on the **update** path returns *before* the
per-section loop — so an id carries neither charset nor length bound. Verified:
an id containing newlines and `---` runs emitted a fully forged top-level block.
The same unverified-assumption pattern that caused the original bug, one layer
down. Fixed at the class, not the instance: `_screened_fragment` is now the only
way any clinician value reaches the prompt, fallbacks included, ending at a
constant.

**2. The sanitizer's character classes were incomplete.** Python's `\s` does not
match zero-width characters, and `-{2,}` only ever matched U+002D. So
`-<ZWSP>-<ZWSP>-` and `———` both sailed through, and `you may<ZWSP>diagnose`
evaded the banlist while remaining invisible in any template editor. Now:
invisibles → **space** (not deleted — deleting would rejoin the hyphens into a
real fence *and* leave `you maydiagnose` unmatched; a space defangs the fence
and reunites the phrase so the banlist fires), Unicode dashes normalise to
ASCII, spaced hyphen runs collapse, tag-shaped runs go (Claude is XML-steered
and `anthropic.py` is a live provider), and the title's quote delimiter is
stripped. Legit clinical prose is untouched — `peri-wound`, `20-30 degrees`,
`state-of-the-art`, `Lesion < 2cm` all survive byte-identical, asserted.

**3. Grounded mode silently unlocked diagnosis on this path.** `validate_specialty_guidance`
is mode-aware; with `grounded_synthesis_enabled` ON it drops **13** phrases —
every clinical role-flip among them (`you may diagnose`, `interpret the
findings`, `recommend treatment`). Sound for note-gen, where the critique pass
and citation validators still catch an ungrounded claim. **Not** sound here: a
caption becomes a `NoteClaim` directly. Flipping the grounded flag would have
made "You may diagnose from the image" an acceptable template description on
the one path with no backstop. New `validate_vision_guidance` pins this path to
the descriptive banlist regardless of mode.

**4. The one fail-CLOSED path.** `resolve_session_template` was awaited
unguarded. Stage 2 has no degrading wrapper — `_run_stage2_in_background` marks
the job FAILED and fires a CRITICAL alert — so a `ValueError` from `get_template`
or a DB error inside `custom_templates` (a table Stage 2 never touched before
this slice) turned *"your guidance was unavailable"* into *"your note didn't
generate"*. Now wrapped; the plan's own "fail safe, never fail closed" rule is
actually enforced.

**5. The flag is now read once per run.** It was read per evidence item, and
`get_config()` is a 30s poller against a <5-min Stage 2 SLA — so a mid-run flip
could produce one note with half its captions aimed and half not. The decision
moved to the route and `_section_focus_block` became a pure function of its
inputs; `template is None` **is** the off switch.

**6. `api/v1/vision.py` had zero test coverage**, and AC-6/AC-7 named tests that
were never written (the earlier commit claimed this was fixed; only AC-3 was).
The load-bearing "a dark path stays dark end-to-end" claim was entirely
unasserted. Now four real route tests, including one proving the DB round-trip
does not happen with the flag off.

**Test-quality fixes from the same pass:** the tautological AC-3 test (which
asserted on a string the test itself concatenated) is gone, replaced by
properties that are actually properties of the block; the real-composition test
now passes a physician override, because `SessionModel.clinician_id` is
non-nullable and the previous version drove an `or VISION_SYSTEM_PROMPT`
fallback that is **unreachable in production**; the length-cap assertion was
loose enough to let `_FRAGMENT_MAX` regress from 600 to ~880 unnoticed; and two
fixtures shared the string `"Wound assessment"` so a routing assertion could not
tell correctness from coincidence.

**All 11 fixes were mutation-tested** — each fix reverted in turn, confirming
the corresponding test fails without it.

## Known limit: prediction and placement can disagree (tier 3)

`_find_target_section` is one router used for both prediction (TE-3) and
placement (the merge), and tiers 1-2 genuinely agree. **Tier 3 does not.**
`merge_visual_citations` flips its target from `pending_video` to `populated`
as it goes, and REPEATS captions are dropped between the two calls — so on a
custom template whose section ids fall outside the hardcoded tier-2 tuple
(exactly the templates this epic exists for), two frames can be captured under
one section's guidance and filed under two.

A quality ceiling on TE-3, not a safety issue: guidance only aims the
description, and the claim keeps its `source_id` either way. **TE-4 is the
fix** — routing on the template's own sections and keywords instead of the
hardcoded tuple. Pinned in `::test_tier3_prediction_and_placement_can_disagree`
rather than papered over, and the docstring no longer claims consistency it
doesn't have.

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

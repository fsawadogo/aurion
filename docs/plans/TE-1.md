# Plan — TE-1 (backend)

## Task

Put note verbosity under template/session control. Replace the single hardcoded *"capture EVERY distinct point"* directive (`providers/note_gen/shared.py:259`) with a **graded** capture directive driven by a `detail_level` (`brief` | `standard` | `detailed`), resolved from the session override → the template → the default.

## Why

**The other half of Marie's complaint, still unaddressed.** *"Trop verbeuse… encombré de détails non pertinents."* TE-3/TE-4 killed the *frame-caption* clutter. The *transcript* half is still hardcoded maximalist (`shared.py:259`) and **test-locked** (`test_note_completeness_prompt.py:42-47`), so every note captures EVERY point whether the clinician wants that or not. This is the direct verbosity control.

## The safety line this slice must hold

The directive is test-locked for a reason: *"so it doesn't summarize the encounter down to a handful of claims."* Dropping clinical content is the danger. So:

- **`brief` reduces verbosity on MINOR / incidental points, never on the essentials.** Its directive must explicitly keep findings, diagnoses discussed, decisions, medications, and the plan — and only trim routine negatives, small talk, and repetition. Brief ≠ incomplete.
- **`detailed` is byte-identical to today** (the exact current directive string).
- **Descriptive mode is untouched** — this changes *how much* is captured, never whether the model may interpret. No level authorizes inference.

## Scope (backend only; web is TE-1b)

The epic wanted web parity in-slice, but the backend graded directive + resolution is independently testable and is the risky half. **TE-1 ships the backend; TE-1b wires the Brief/Standard/Detailed rail control already designed in #662** (mirrors the TE-2→TE-3 split). Without TE-1b the field is dark, so TE-1b is a hard follow-on, tracked.

## Approach

1. **`core/types.py`** — `Template` gains `detail_level: Optional[Literal["brief","standard","detailed"]] = None`. `None` = today's behaviour. Session gains the same as a per-session override (mirrors `output_language`).
2. **Resolution** — `session.detail_level` → `template.detail_level` → `None`. One helper, next to the template pin resolution.
3. **`providers/note_gen/shared.py` `build_user_prompt`** — render the directive from the resolved level:
   - **`None` / `detailed`** → the current string, verbatim (byte-identical).
   - **`standard`** → capture the clinically significant points; group minor related details; omit incidental repetition and small talk.
   - **`brief`** → capture the key findings, decisions, medications and plan as distinct claims; omit routine negatives and minor detail unless clinically relevant. Still one claim per significant point.
4. **Flag** — gated by `template_engine_enabled`, per the epic's one-flag rule. **OFF → the exhaustive directive regardless of `detail_level`** (byte-identical). ON → graded. So Cohort 7 flips as one switch.
5. **The test lock** — NOT weakened. `test_user_prompt_demands_exhaustive_capture` keeps asserting the maximalist directive is present **for the default / detailed / flag-off cases** (that safety property still holds there). New tests cover brief/standard rendering a *different* directive, and the byte-identical guarantees.

## Acceptance criteria

- [ ] **AC-1:** flag OFF → prompt byte-identical to today for every `detail_level` — `test_te1_detail_level.py::flag_off_is_byte_identical`
- [ ] **AC-2:** flag ON, `detail_level=None` or `detailed` → the exhaustive directive, verbatim — `::detailed_matches_today`
- [ ] **AC-3:** flag ON, `brief` → a shorter directive that still names findings/decisions/medications/plan and forbids dropping clinical content — `::brief_trims_minor_not_essential`
- [ ] **AC-4:** `standard` differs from both — `::standard_is_between`
- [ ] **AC-5:** resolution order session > template > None — `::session_override_beats_template`
- [ ] **AC-6:** the existing completeness lock still passes for the default case (not weakened) — existing test green
- [ ] **AC-7:** no level relaxes descriptive mode (no "interpret/diagnose/infer" wording enters any directive) — `::no_level_authorizes_inference`
- [ ] **AC-8:** full `tests/unit/` green; ruff clean; `/health` 200; zero iOS/web diff

## Out of scope

- **TE-1b** — the web Brief/Standard/Detailed control + session-create wiring.
- Changing `max_tokens` or the schema.
- Any frames/vision path (TE-3/TE-4, shipped).

## Security / safety

- **Completeness is a clinical-safety property.** The plan's whole point of tension: making notes shorter must not drop clinical content. The directives are written so `brief` trims *incidental* material only, and a test asserts the essentials are still demanded.
- **Descriptive mode preserved** — AC-7 asserts no level introduces interpretive wording.
- **Flag OFF byte-identical** — AC-1, the rollout safety net.

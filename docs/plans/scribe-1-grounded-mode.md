# Plan — scribe-1 (#621): Grounded Synthesis as a true mode

## Task
When Grounded Synthesis Mode is on, the grounded system prompt is an
always-enforced safety boundary; personal / template / published prompts become
**additive** style layers instead of full replacements.

## Why
`grounded_synthesis_enabled` today only swaps the base default
(`prompts/assembly.py::resolve_base_system_prompt`); the cascade is replacement
semantics, so any override REPLACES the grounded boundary and the flag is
silently bypassed — the root cause of "flag on but notes still descriptive."
This makes grounded a real mode. CLAUDE.md "Single Most Important Constraint"
(Grounded Synthesis Mode, #551/#552). Context: `memory/grounded-scribe-gap-map.md`.

## Approach
- `assembly.py`: add `_grounded_note_gen` + `_compose_system_prompt`
  (boundary-always-on + additive in grounded mode; byte-identical replacement
  otherwise). Route `assemble_prompt` and BOTH `assemble_prompt_for_session`
  fallbacks (bad-uuid, missing-clinician) through it — the missing-clinician
  path also stops returning the raw descriptive default (P3 fix).
- `me_prompts.py::_serialize`: report `resolve_base_system_prompt` (grounded-
  aware) for the default `active_prompt` and the `system_prompt` field, so the
  AI Prompts page shows the boundary that actually runs.

## Acceptance criteria
- [ ] AC-1: grounded ON + descriptive template `system_prompt` → assembled prompt starts with the grounded boundary AND contains the template text (appended, not substituted).
- [ ] AC-2: grounded ON + publication (no personal/template) → boundary + appended.
- [ ] AC-3: grounded ON + missing/bad session → grounded base, not raw descriptive default.
- [ ] AC-4: transparency `_serialize` default reports the grounded base when the flag is ON.
- [ ] AC-5 (regression): flag OFF → replacement byte-identical (personal > template > published > base).
- [ ] AC-6: grounded ON + non-note_generation prompt → replacement (unchanged).

## DRY / SOLID check
- Reused: `resolve_base_system_prompt` (single grounded-swap site), `_get_user_prompt`, `_get_published_prompt`.
- New helper `_compose_system_prompt` replaces three copies of the resolve-cascade tail (`assemble_prompt` + both session fallbacks) — a justified extraction crossing the grounded/legacy boundary. No new `if provider ==` branch (OCP).

## Out of scope (moved to sibling issues)
- Parse-time `source_id` membership validation → #624 (scribe-4).
- Save-time validator anchor relaxation + descriptive/thinning banlist, and neutralizing descriptive text that survives as an additive layer → #622 (scribe-2).
- Render/export → #625. iOS default-context → #623.

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/test_scribe1_grounded_additive.py -q`
2. Regression: `python -m pytest tests/integration/test_prompt_resolution.py tests/unit/test_me_prompts_serialize.py tests/unit/test_grounded_synthesis_prompt.py -q`

## Security implications
- Changes the AI-output boundary — the sanctioned Grounded Synthesis Mode path (#551/#552), dark behind `grounded_synthesis_enabled` (default OFF → every path byte-identical; GS-9 gates flipping on). STRENGTHENS the floor: no override can strip the grounded boundary. No PHI; no new AI call; no consent/masking/audit path touched.

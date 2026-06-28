## Task
GS-1 (#543) — note-gen system prompt: allow grounded synthesis (flag-gated, dark)

## Why
Gate #1, the primary behaviour driver (CLAUDE.md "Single Most Important Constraint").
Today rules 2 & 5 forbid synthesis. Under v3.2 Grounded Synthesis (#552) we allow
synthesizing an Assessment & Plan FROM cited findings — grounded, never speculative.
Ships DARK behind grounded_synthesis_enabled (GS-7, #549); live output unchanged until
GS-9 sign-off (#551).

## Approach
- `providers/note_gen/shared.py`: add NOTE_GEN_GROUNDED_SYSTEM_PROMPT (keeps rules 1/3/4
  on traceability + no-fabrication; rewrites 2 & 5 to permit grounded, cited synthesis).
- `prompts/assembly.py`: add `resolve_base_system_prompt(prompt_id)` — returns the grounded
  note_generation base iff feature_flags.grounded_synthesis_enabled, else the registry
  default. Replace the two `PROMPTS[prompt_id].system_prompt` base-default sites with it.
  ONLY note_generation is affected; vision/reconcile/preview stay literal (GS-8 keep-list).
- Overrides/published/template prompts still win over the base (unchanged cascade).

## Acceptance criteria
- [ ] AC-1: flag OFF → `resolve_base_system_prompt("note_generation")` is byte-identical to NOTE_GEN_SYSTEM_PROMPT — `test_grounded_synthesis_prompt.py`
- [ ] AC-2: flag ON → returns NOTE_GEN_GROUNDED_SYSTEM_PROMPT — same test
- [ ] AC-3: flag ON → `resolve_base_system_prompt("vision_frame")` unchanged (only note_gen affected) — same test
- [ ] AC-4: grounded prompt requires grounding (contains cite/traceable/grounded) and still forbids fabrication; descriptive base unchanged — same test
- [ ] AC-5: existing prompt-assembly + note-gen tests stay green (no behaviour change with flag OFF)

## DRY / SOLID check
- **Reuse**: `PROMPTS` registry, `get_config().feature_flags`, existing cascade in assemble_prompt. One new resolver (the THIRD+ base-default read site → extraction justified).
- **OCP**: behaviour added via flag branch in one resolver, not scattered ifs.

## Out of scope
Validator anchors (GS-4), specialty style (GS-3), examples (GS-2), CLAUDE.md (GS-5),
multi-anchor schema (GS-6). Flipping the flag (GS-9). The live preview/vision prompts.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_grounded_synthesis_prompt.py -q`
2. `python3 -m pytest tests/unit/test_prompt_assembly_safety.py tests/unit/test_prompt_resolution_precedence.py tests/unit/test_note_gen.py -q`

## Security implications
NEW AI prompt allows synthesis → the "Descriptive mode" security box CANNOT be auto-ticked.
But it is gated behind grounded_synthesis_enabled (OFF) so LIVE output stays descriptive
(AC-1). Requires human review + GS-9 sign-off before enable. No PHI / audit / registry change.

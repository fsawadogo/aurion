## Task
GS-4 (#546) — safety validator: descriptive anchors/banlist → grounding (flag-gated)

## Why
Gate #4, the configuration lock. Today `prompts/safety.py` rejects any SAVED
custom prompt (Prompt Studio / per-physician replacement) that lacks "do not
interpret" anchors or contains "make a diagnosis" etc. — so even a deliberately
grounded-synthesis prompt is blocked at save. Under v3.2 (#552) the validator
must require GROUNDING (cite/traceable) instead of forbidding interpretation.
Flag-gated: OFF = today's descriptive validator (byte-identical); ON = grounding.

## Approach
- Add `GROUNDED_BANNED_PHRASES` (keep injection/role-flip/override vectors; DROP
  the diagnose/interpret/treatment bans — grounded synthesis allows those when cited)
  and `GROUNDED_ANCHORS_REQUIRED` (Group 0 describe/document/synthesize; Group 1
  GROUNDING: cite/traceable/grounded/source).
- `validate_user_prompt` selects banlist + anchors via
  `get_config().feature_flags.grounded_synthesis_enabled`. OFF → existing
  BANNED_PHRASES + DESCRIPTIVE_ANCHORS_REQUIRED (unchanged).
- Injection/override vectors (`ignore previous instructions`, `system prompt
  override`, …) stay banned in BOTH modes.

## Acceptance criteria
- [ ] AC-1: flag OFF → validator behaviour byte-identical to today (existing `test_prompt_assembly_safety.py` green)
- [ ] AC-2: flag ON → a grounded prompt ("synthesize… cite every claim to its source… traceable") PASSES even though it mentions diagnosis/plan
- [ ] AC-3: flag ON → a prompt MISSING grounding anchors fails MISSING_DESCRIPTIVE_ANCHOR
- [ ] AC-4: injection vector (`ignore previous instructions`) is BANNED in both modes
- [ ] AC-5: flag ON → `make a diagnosis` / `recommend treatment` are NO LONGER banned (a grounded prompt containing them, with grounding anchors, passes)

## DRY / SOLID check
- **Reuse**: the existing matcher loops, ValidationResult/ValidationCode, get_config pattern. New constants mirror the existing tuples (parallel grounded set), one flag branch in validate_user_prompt.
- **OCP**: behaviour added via flag-selected constant sets, not new branches per phrase.

## Out of scope
The note-gen prompt (GS-1, done), specialty style (GS-3), examples (GS-2), CLAUDE.md (GS-5). Flipping the flag (GS-9).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_prompt_assembly_safety.py -q` (OFF unchanged)
2. `python3 -m pytest tests/unit/test_grounding_validator.py -q` (ON behaviour)

## Security implications
RELAXES the descriptive-mode save gate when the flag is ON — the "Descriptive
mode" security box CANNOT be auto-ticked. Gated behind grounded_synthesis_enabled
(OFF) so the LIVE save gate stays descriptive (AC-1). Injection/override defence is
preserved in both modes. Human review + GS-9 sign-off required before enable.

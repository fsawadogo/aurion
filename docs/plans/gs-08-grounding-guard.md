## Task
GS-8 (#550) — keep the grounding gates intact + regression test (the differentiator)

## Why
Grounded synthesis is only safe because the grounding gates stay strong: critique
drops unanchored claims, every claim needs a source anchor, and vision/reconcile
stay literal. This slice (a) extends the critique anchor check to validate GS-6
additional_sources (so a synthesized claim citing a FABRICATED extra source is
flagged), and (b) adds a regression test pinning the grounding invariants.

## Approach
- `note_gen/critique.py`: in `_build_critique_prompt`, also surface each claim's
  additional_sources ids + their validity (extra_valid) so the critic can drop a
  claim whose extra anchor isn't a real segment. Primary-anchor behaviour unchanged.
- New `tests/unit/test_grounding_guard.py`: pins the invariants — anchorless claim
  impossible (Pydantic), critique flags invalid primary AND invalid additional
  anchors, _apply_actions drops a claim, all_source_ids enumerates every anchor.

## Acceptance criteria
- [ ] AC-1: NoteClaim/ClaimSource reject empty source_id (no anchorless claim) — test
- [ ] AC-2: critique prompt marks valid=False for an out-of-transcript primary source — test
- [ ] AC-3: critique prompt marks extra_valid=False when an additional_source is fabricated — test
- [ ] AC-4: _apply_actions drops a named claim (mechanical grounding cleanup works) — test
- [ ] AC-5: a fully-grounded multi-anchor claim shows valid=True + extra_valid=True — test

## DRY / SOLID check
- **Reuse**: _build_critique_prompt, _apply_actions, NoteClaim.all_source_ids (GS-6). Small additive surfacing in one function.

## Out of scope
LLM-driven drop decision (covered by existing test_note_critique with a mocked provider). Flipping any flag.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_grounding_guard.py tests/unit/test_note_critique.py -q`

## Security implications
STRENGTHENS the grounding gate (additional_sources now audited). No prompt-policy
change; not flag-gated (the gate applies in both modes — grounding is always
required). Descriptive-mode box TICKABLE. No PHI/audit/registry change.

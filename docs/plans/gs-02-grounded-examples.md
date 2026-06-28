## Task
GS-2 (#544) — grounded-synthesis few-shot examples (flag-gated), pilot specialties

## Why
Gate #2 — the few-shot examples are a strong steer. Today every A&P example is a
verbatim physician quote ("echo, never synthesize"). Under v3.2 (#552) we add a
worked example that SYNTHESIZES the A&P from multiple cited findings (using GS-6
additional_sources). Flag-gated; OFF = today's descriptive examples only.

## Approach
- `note_gen/few_shot.py`: load grounded examples from `{key}.grounded.examples.json`
  and APPEND them only when feature_flags.grounded_synthesis_enabled is ON. Cache raw
  file loads separately; combine at call time so OFF is byte-identical.
- New `orthopedic_surgery.grounded.examples.json` + `plastic_surgery.grounded.examples.json`
  (the 2 pilot specialties): each a transcript → ideal note whose assessment claim is
  synthesized from ≥2 cited sources (primary source_id + additional_sources). Other
  specialties: follow-up.

## Acceptance criteria
- [ ] AC-1: flag OFF → get_few_shot_examples(k) == descriptive examples only (byte-identical) — test
- [ ] AC-2: flag ON → ortho/plastic include the grounded example (≥1 claim with additional_sources) — test
- [ ] AC-3: every claim in the grounded examples has a non-empty source_id (grounding integrity) — test
- [ ] AC-4: grounded example JSON loads + renders without error — test
- [ ] AC-5: existing few-shot tests stay green (OFF default)

## DRY / SOLID check
- **Reuse**: get_few_shot_examples loader + cache + render_examples_block (unchanged). One flag branch + a parallel grounded file loader.

## Out of scope
Non-pilot specialties' grounded examples (follow-up). Flipping the flag (GS-9).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_grounded_examples.py tests/unit/test_specialty_prompts.py -q`

## Security implications
Grounded examples teach synthesis → only injected when the flag is ON (OFF byte-identical).
Every example claim is source-anchored (grounding preserved). Descriptive-mode box
unticked (the examples model synthesis). Human review + GS-9 before enable.

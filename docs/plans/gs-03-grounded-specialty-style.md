## Task
GS-3 (#545) — specialty style guidance: anti-synthesis → grounding-required (flag-gated)

## Why
Gate #3. Today each MVP specialty's style snippet ends with an anti-synthesis
clause ("never add differentials and never interpret findings", etc.). Under v3.2
(#552) these must reinforce GROUNDED synthesis (synthesize, but cite every claim)
rather than re-block it. Flag-gated; OFF = descriptive snippets unchanged.

## Approach
- `note_gen/specialty_style.py`: add `_GROUNDED_STYLE` with grounded variants for the
  5 MVP specialties (same body, final clause swapped to grounding-required). Parallel
  dict (not string surgery) so each clinical snippet is independently reviewable.
- `get_specialty_style` returns the grounded variant iff
  feature_flags.grounded_synthesis_enabled AND a grounded variant exists, else the
  descriptive snippet. Post-MVP specialties (no anti-synthesis clause) fall through.

## Acceptance criteria
- [ ] AC-1: flag OFF → `get_specialty_style(k)` byte-identical to `_STYLE[k]` for all keys
- [ ] AC-2: flag ON → the 5 MVP specialties return a grounded variant that mentions cite/grounded and drops "never interpret/infer/add differentials"
- [ ] AC-3: flag ON → a post-MVP specialty (e.g. pediatrics) is unchanged (no grounded variant)
- [ ] AC-4: grounded variants still forbid UNSUPPORTED conclusions (contain "cite"/"support")

## DRY / SOLID check
- **Reuse**: `_STYLE`, get_config pattern. New `_GROUNDED_STYLE` mirrors the 5 MVP entries (clinical text — explicit-over-clever for reviewability; only the synthesis clause differs).
- **OCP**: one flag branch in get_specialty_style.

## Out of scope
GS-2 examples, GS-6 multi-anchor, GS-5 CLAUDE.md. Flipping the flag (GS-9). Post-MVP specialties.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_grounded_specialty_style.py tests/unit/test_specialty_prompts.py -q`

## Security implications
Relaxes specialty-style anti-synthesis when ON → descriptive-mode box unticked.
Gated behind grounded_synthesis_enabled (OFF) so live snippets stay descriptive (AC-1).
No PHI/audit/registry change. Human review + GS-9 sign-off before enable.

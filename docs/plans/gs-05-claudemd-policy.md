## Task
GS-5 (#547) — CLAUDE.md: policy source of truth → Grounded Synthesis Mode

## Why
Gate #5. CLAUDE.md is the policy every prompt/code change is written against; if
it keeps saying "exclusively Descriptive Mode," the descriptive rules grow back.
Redefine the constraint to document Grounded Synthesis (v3.2, #552) as the
sanctioned beyond-descriptive path — flag- + sign-off-gated, grounding mandatory.

## Approach
- Rewrite "The Single Most Important Constraint" to define BOTH modes: Descriptive
  (default, flag OFF) and Grounded Synthesis (flag ON, dark until GS-9 sign-off,
  every statement cited). Ungrounded interpretation / fabrication forbidden in BOTH.
- Add a grounded ✅/❌ example (cited synthesis OK; uncited conclusion never).
- "What NOT to Build": "Interpretative AI / Diagnostic inference" →
  "Ungrounded interpretation / uncited diagnostic inference".

## Acceptance criteria
- [ ] AC-1: constraint section names both modes + the flag + GS-9 gate
- [ ] AC-2: grounding ("cite"/"source") is mandatory in the grounded example
- [ ] AC-3: ungrounded/fabrication still forbidden in both modes (explicit)
- [ ] AC-4: doc-only; no code/test references the changed prose (grep clean)

## DRY / SOLID check
- Doc change; n/a. (The flag name matches FeatureFlagsConfig.grounded_synthesis_enabled.)

## Out of scope
Code behaviour (GS-1/3/4 do that, flag-gated). Flipping the flag (GS-9).

## Test plan (executable)
1. `grep -rn "operates exclusively in Descriptive" backend ios web` → no code depends on the old wording
2. Visual review of the rewritten section.

## Security implications
This is THE policy change that sanctions grounded synthesis. It documents that
the mode is dark (flag OFF) until clinical + regulatory sign-off (#551), and that
ungrounded output is forbidden in both modes. Descriptive-mode box deliberately
left unticked — this PR is the constraint redefinition itself; gated on GS-9.

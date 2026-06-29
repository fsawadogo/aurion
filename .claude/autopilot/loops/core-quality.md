# Loop: core-quality eval

## Loop spec
- **GOAL** — exercise THIS product's core function (the audio→Stage-1 note
  pipeline + the descriptive/grounded behavior) and assert it still works; file
  regressions.
- **VERIFY** — a regression is real only if a deterministic check fails:
  `workflows/core-quality.js` runs the golden/smoke assertions and the verifier
  panel confirms the failure is a true regression (not a flaky/env issue) by
  re-running. No reproducible failure ⇒ no finding.
- **STOP WHEN** — the core-function checks all pass, OR confirmed regressions are
  filed up to `caps.max_findings_per_run`.
- **ON STOP** — pass/fail summary; issues for confirmed regressions; `log-run`.

## Need a loop? (verdict: YES → autonomy `propose-only`)
repeats ✓ (daily) · auto-reject ✓ (assertions pass/fail) · end-to-end ✓ ·
objective ✓. Files regressions (doesn't fix — root cause needs human triage).

## Specifics
- **Core checks** (objective, no PHI; use fixtures, not pilot data):
  - `pytest tests/unit -q` green (the contract suite).
  - note-gen schema invariants: every claim source-anchored; descriptive prompt
    byte-identical with the grounded flag OFF; grounded path cited when ON
    (reuse `test_grounded_synthesis_*`, `test_grounding_guard`).
  - prompt-assembly cascade + provider-registry parity (all providers same schema).
  - flag OFF/ON integration smoke (the descriptive↔grounded switch).
- finders on `models.finder` propose candidate weak spots / missing assertions;
  the WORK is deterministic test execution — the verifier confirms a failure
  reproduces (re-run) before filing.
- **act** (`propose-only`): open an issue per confirmed regression
  (`autopilot`,`autopilot:quality`), with the failing command + output. NEVER
  auto-fixes core pipeline (it's protected-adjacent).
- **record**: fingerprint = `quality:<check-id>`; accepted = a human merges a fix /
  the check, rejected = dismissed as expected change.

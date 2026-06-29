# Loop: enhancement ideation

## Loop spec
- **GOAL** — propose code-grounded improvements (DX, perf, test coverage,
  small UX), vetted for novelty + value; file as issues.
- **VERIFY** — judge panel (`workflows/enhancement.js`, `models.judge`): each idea
  scored on (is it grounded in real code? is it novel vs the backlog/issues? is
  the value worth the effort?); keep only ideas a majority rate "worth filing."
  Defaults to "not worth it."
- **STOP WHEN** — ≤ `caps.max_findings_per_run` vetted ideas filed, or none pass.
- **ON STOP** — filed ideas + the ones rejected (and why); `log-run`.

## Need a loop? (verdict: WEAK → autonomy `propose-only`, low cadence)
repeats ✓ · auto-reject ✗ (value is taste) · end-to-end ✗ · objective ✗. This is
the loop most likely to fall under `min_accept_rate` — the digest watches it
hardest; if accept-rate < 50% it gets throttled. **Files only, never builds.**

## Specifics
- finders (`models.finder`) read real code (hot paths, TODO/FIXME, test gaps,
  slow tests) and propose grounded ideas — each must cite file:area.
- **novelty gate**: dedup against existing open issues (`gh issue list`) AND the
  ledger — an idea matching an open issue/finding is dropped (not refiled).
- **value gate**: judge panel must agree value ≥ effort; pure-taste ideas dropped.
- **act** (`propose-only`): issue per surviving idea (`autopilot`,
  `autopilot:enhancement`) with the code grounding + a rough effort estimate. No PRs.
- **record**: fingerprint = `enh:<area>:<slug>`; accepted = a human acts on it,
  rejected = closed/ignored. Low accept-rate here is expected — keep caps tight.

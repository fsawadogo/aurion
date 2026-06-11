# OV-6 — Branch protection / required-checks gate (#265) — DESIGN, DEFERRED

**Status: NOT executed by the overnight loop (deliberate).** This changes
the merge mechanics the loop itself depends on; a wrong config deadlocks
`main` (or breaks auto-merge) with no human present to recover. Deferred
to a supervised change, per the same posture as OV-5 (auth → human merge).
The autonomous_authority is "auto-merge on green CI" — adding a required-
checks ruleset is a governance change above that line.

## The hazard (why the naive version breaks)
CI checks are **path-filtered**: a backend-only PR runs `lint`+`test` and
SKIPS `build`/`deploy-dev`; a web PR runs the web workflow; an iOS PR runs
`build`. A GitHub ruleset that REQUIRES `lint`+`test`+`build` would block
every backend-only and web-only PR forever — the required `build` context
never reports on them, so the PR can't satisfy protection. (This is the
exact trap #265 must avoid, and why it's tagged run-last.)

## Recommended design — a single aggregate "gate" check
1. Add a `ci-gate` job to each workflow (ci.yml, web.yml, ios-testflight.yml)
   that `needs:` that workflow's real jobs and runs `if: always()`,
   failing unless every needed job is success/skipped. Each workflow's
   gate reports the SAME check name (`ci-gate`) so it always reports on
   every PR regardless of which stack changed.
2. Branch-protect `main` requiring exactly one status check: `ci-gate`.
   Require PR + 0 stale-review dismissals (keep the loop's flow); do NOT
   require human approval (would halt autonomous merge — that's a separate
   CTO policy decision, cf. #265's intent for auth/pilot-sensitive paths).
3. Verify with a no-op PR per stack (backend, web) that `ci-gate` reports
   and merge still works, BEFORE relying on it.

## Why supervised
- Enabling protection is an admin/governance action; if `ci-gate` is
  misconfigured, `main` locks and the loop can't self-recover.
- It should land when the CTO can watch the first few gated merges.
- Pairs naturally with the CTO's call on whether auth/pilot-sensitive PRs
  (screen.py, frames.py, MaskingPipeline, audit writers — workflow §17)
  get a hard human-approval requirement in the same ruleset.

## Suggested next step
A small supervised PR adding the three `ci-gate` jobs (no protection yet),
merged + observed reporting on a few PRs, THEN enable the ruleset.

# Loop: digest (meta-loop) — runs LAST

## Loop spec
- **GOAL** — reconcile every loop's findings against LIVE PR/issue state, compute
  accept-rate + cost-per-accepted per loop, dedupe, rank open items by
  severity × effort, and emit ONE prioritized summary so the loops never drown
  you in noise.
- **VERIFY** — reconciliation is deterministic (ledger ↔ `gh` state); the digest
  asserts its own numbers (counts reconcile, no double-count) before sending.
- **STOP WHEN** — the single digest is produced + delivered.
- **ON STOP** — digest delivered (email/file); `log-run`.

## Need a loop? (verdict: YES → autonomy `propose-only`)
repeats ✓ (weekdays) · auto-reject ✓ (reconciliation is exact) · end-to-end ✓ ·
objective ✓. It's the cost-control + noise-control brain. Files/sends only.

## Specifics
- **reconcile** each ledger finding with live state:
  `gh pr view <pr> --json state,mergedAt` / `gh issue view <n> --json state` →
  set `resolve <fp> --status accepted` (merged PR / closed-as-done issue) or
  `rejected` (closed-without-merge / dismissed). Open items stay open.
- **the metric**: run `ledger.py stats --json`. For any loop with
  `accept_rate < min_accept_rate` (the `below_min` flag), RECOMMEND
  throttle/tune (tighten caps, sharpen finders, or drop to propose-only) and call
  it out at the TOP of the digest. Report **cost-per-accepted** per loop.
- **rank** open findings by severity × (1/effort); cap the surfaced list — note
  the overflow count, don't dump everything.
- **deliver** (`propose-only`): build the digest markdown →
  - if `email.channel == resend` and the Resend key is reachable (Secrets
    Manager), send the summary via the project's Resend integration;
  - else (headless / no email) write `state/digests/<date>.md` and print the path.
  Never opens PRs.
- `workflows/digest.js` is light: a verifier-tier pass that sanity-checks the
  ranking + the accept-rate call-outs (no finders).
- **record**: `log-run digest --status … --note "<loops flagged below min>"`.

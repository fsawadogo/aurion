# Loop: pr-review

## Loop spec
- **GOAL** — review each open PR (correctness / security / project conventions),
  verify the findings, post ONE consolidated advisory comment per PR.
- **VERIFY** — each candidate issue goes through the refute panel
  (`workflows/pr-review.js`, `models.verifier`): keep only findings ≥2 verifiers
  confirm against the actual diff. Drops nitpick/false-positive noise.
- **STOP WHEN** — every open PR (not authored by Autopilot) has a current review
  comment, OR caps/budget hit.
- **ON STOP** — per-PR comment posted; `ledger.py log-run`.

## Need a loop? (verdict: PARTIAL → autonomy `propose-only`, ADVISORY)
repeats ✓ · auto-reject ✗ (review quality is judgement) · end-to-end ✗ · objective ✗.
Quality is taste ⇒ **file/advise, never merge**. Never merges others' PRs.

## Specifics
- gather open PRs: `gh pr list --state open --json number,headRefName,author`.
  Skip PRs labelled `autopilot` (don't review our own). Re-review only on new commits
  (dedup fingerprint = `pr:<number>:<head-sha>`).
- finders (`models.finder`) per dimension (correctness, security, conventions,
  test-coverage); verifier panel (`models.verifier`) confirms against the diff.
- **gate**: advisory only — never merges, so the gate is informational; still flag
  if the PR touches `protected_paths` ("this PR changes a protected area — needs
  human merge per AURION-CODING-WORKFLOW §17").
- **act**: post ONE consolidated `gh pr comment <n>` (label note `autopilot:review`).
  No merge, ever.
- **record**: `ledger.py record pr-review --fingerprint pr:<n>:<sha> --issue <n>`;
  accepted = the author acted on a flagged item (digest reconciles); else rejected.

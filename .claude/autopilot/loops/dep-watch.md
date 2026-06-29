# Loop: dependency / CVE watch

## Loop spec
- **GOAL** — scan deps (backend `requirements*.txt`/`pyproject`, web
  `package.json`, iOS SPM) for outdated/vulnerable versions; auto-merge SAFE
  bumps when green; escalate risky ones.
- **VERIFY** — refute panel (`workflows/dep-watch.js`, `models.verifier`): a bump
  is "safe" only if ≥2 verifiers confirm it's patch/minor with no breaking
  changelog AND the full build/test stays green. Major bumps / changelog
  break-risk default to "not safe" → escalate.
- **STOP WHEN** — all safe bumps PR'd (≤ `caps.max_prs_per_run`), risky ones
  filed; or budget hit.
- **ON STOP** — bumps merged/escalated summary; `log-run`.

## Need a loop? (verdict: YES → autonomy `low-risk`)
repeats ✓ (weekly) · auto-reject ✓ (green build + semver) · end-to-end ✓ ·
objective ✓. `deps` ∈ `auto_merge_categories` ⇒ safe bumps MAY auto-merge.

## Specifics
- gather: `pip list --outdated` (in backend venv), `npm outdated` (web), SPM
  resolved; cross-ref CVEs (`pip-audit` / `npm audit` if present).
- **Each bump in its own worktree** (`worktree_isolation`): apply, run
  `commands.backend_test`/`web_build`, capture green/red.
- **gate**: `ledger.py gate --files requirements.txt` etc. Lockfiles are NOT in
  protected_paths → clear. BUT a bump that drags in a change to any protected
  path, or to a security-critical lib's pinned behavior, ⇒ escalate.
- **act** (`low-risk`): patch/minor + green + verifier-confirmed-safe → auto-merge
  (category `deps`). Major / red / break-risk → `needs-human` PR or issue.
- **record**: fingerprint = `dep:<pkg>:<from>-><to>`; merged = accepted, escalated
  = open. One PR per package, minimal diff (the lockfile + manifest only).
- **outputs**: PR per bump (`autopilot`,`autopilot:deps`; +`needs-human` if risky).

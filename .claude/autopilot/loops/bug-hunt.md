# Loop: bug-hunt

## Loop spec
- **GOAL** — find real bugs in this stack's high-risk classes, fix the verified
  ones in isolated worktrees, auto-merge if green + non-protected, else escalate.
- **VERIFY** — adversarial refute panel (`workflows/bug-hunt.js`): 3 verifiers on
  `models.verifier`, each defaulting to "not a real bug"; ≥2 must confirm with a
  concrete repro/trace. Then the fix must produce a **green build + a regression
  test that fails pre-fix**. No green test ⇒ not actionable ⇒ escalate.
- **STOP WHEN** — no new confirmed bugs (deduped) OR `caps.max_prs_per_run`
  reached OR `caps.iteration_cap` OR `token_budget_per_run` hit.
- **ON STOP** — summary of fixed/escalated/rejected; `ledger.py log-run`.

## Need a loop? (verdict: YES → autonomy `low-risk`)
repeats ✓ (weekly) · auto-reject ✓ (failing build/test rejects) · end-to-end ✓
(find→fix→verify→PR) · objective ✓ (build/test pass). Mutating ⇒ worktrees +
auto-merge ONLY non-protected green fixes; protected/prompt/PHI ⇒ escalate.

## Specifics
- **Bug classes to hunt** (this stack): async/await misuse + un-awaited coroutines;
  missing `await write_audit` / audit-write paths; Pydantic validation gaps;
  SQLAlchemy async session misuse / N+1; provider-registry bypass
  (`if provider ==`); unhandled None / KeyError on `.get`; iOS `@MainActor`
  isolation + force-unwraps; missing EN/FR string parity; SQL/transaction leaks.
- **Finders** run on `models.finder` (cheap), one per class, in parallel — blind
  to each other (multi-modal sweep). **Verifiers/fixers** on the strong models.
- **gate**: run `ledger.py gate --files <diff files>` on each fix branch. Exit 2
  ⇒ `needs-human` PR (no merge). A finding touching `domain_sensitive_keywords`
  ⇒ escalate even if the diff looks clean.
- **act** (`low-risk`): a bug FIX is not in `auto_merge_categories` (docs/deps/
  tests) → by policy it opens a **PR for review** (green + gate-clear + standards),
  NOT auto-merge. (Only `full` autonomy would self-merge a verified non-protected
  fix.) Each fix in its own worktree under `worktree_root`.
- **record**: `ledger.py record bug-hunt --fingerprint <fp> --title … --files … --pr N`;
  fingerprint key = `<file>` + `<bug-class/title>` (NOT line). On merge →
  `resolve … accepted`; on close-without-merge → `rejected`.
- **outputs**: PR per fix (label `autopilot`,`autopilot:bug`; +`needs-human` if escalated).

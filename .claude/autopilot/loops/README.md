# Autopilot loops — shared spec

Each `loops/<loop>.md` is the **playbook** a headless `claude -p` run executes.
Each opens with a **Loop spec** and then follows the same skeleton. Read
`../policy.json` for autonomy, models, caps, protected paths, commands.

## Loop spec (every loop states these explicitly)
- **GOAL** — what one tick produces.
- **VERIFY** — the adversarial check that can *fail* the work (no action on an
  unverified finding).
- **STOP WHEN** — the success/stop condition.
- **ON STOP** — what to emit (summary, ledger writes).

## The skeleton (every tick)
1. **gather** — collect inputs (changed files, open PRs, deps, transcripts…).
2. **run workflow** — `Workflow({scriptPath: ".claude/autopilot/workflows/<loop>.js"})`.
   The workflow is **find → adversarially verify → act**, with **maker ≠ checker
   on DIFFERENT models**: finders/ideators on `models.finder` (cheap/fast);
   verifiers/judges on `models.verifier` (strong, high effort); fixers on
   `models.fixer` (strong). Verify is an adversarial **refute panel** that
   defaults to "not real" and needs `verify.confirm_majority` to confirm.
3. **dedup** — for each confirmed finding compute its id with
   `ledger.py fingerprint <loop> <stable-key…>` and skip if `ledger.py seen` is 0.
   Respect `caps.max_findings_per_run`; surface overflow, don't binge.
4. **gate** — for any change, `ledger.py gate --files <changed…>`. Exit 2 ⇒
   PROTECTED ⇒ never auto-merge; open a PR labelled `needs-human`.
5. **act** — per `loops.<loop>.autonomy` (falls back to top-level
   `autonomy_level`):
   - `propose-only` → file issue / draft PR only.
   - `low-risk` → auto-merge ONLY if category ∈ `auto_merge_categories` AND gate
     clear AND green build AND `ENGINEERING_STANDARDS.md` satisfied; else PR.
   - `full` → auto-merge any green, gate-clear, standards-clean change; protected
     still escalates.
   Mutating loops run each change in its OWN git worktree (`worktree_isolation`).
6. **record** — `ledger.py record <loop> --fingerprint <fp> --title … --cost …
   [--pr N|--issue N]`; later `ledger.py resolve <fp> --status accepted|rejected`
   (a merged fix = accepted; a closed-without-merge / dismissed = rejected).
7. **summarize** — write the tick result; `ledger.py log-run <loop> --status … --tokens … --cost …`.

## Hard rules (apply to every loop)
- **Never merge red.** One finding = one branch = one PR, minimal diff, with a
  regression test.
- **Protected gate is absolute** — even at `full`. Protected path OR a
  `domain_sensitive_keywords` topic ⇒ `needs-human` PR, never auto-merge.
- **Cost per accepted change is THE metric.** A loop under `min_accept_rate` over
  its trailing window is surfaced by the digest loop and throttled/tuned.
- **Stop conditions, not just success** — bounded by STOP WHEN + `caps.iteration_cap`
  + `verify` votes + `token_budget_per_run`.
- **Headless email caveat** — interactive MCP email may be absent; the digest loop
  sends via Resend (`email.channel`) or falls back to a file in the state dir.
- **If quality is taste, FILE — don't merge.** (See each loop's "Need a loop?" verdict.)

---
description: Open a PR using the structured Aurion template — Summary, What changed, Why, Test plan, Security checklist, Out of scope, Deferred, Backlog. Pre-ticks security checkboxes the loop can prove; leaves the rest for human verification.
---

# open-pr

Open a pull request for the current In flight task using the Aurion
structured PR template. Pre-tick security checkboxes by greping the diff
for proof; leave unticked anything that requires human judgment.

## Inputs

The skill expects to be called from inside the feature branch, after
`/verify-acceptance` has passed. It reads:

- `.claude/state/in-flight.json` — current task descriptor for this lane.
- The plan file committed earlier in the branch (search for
  `docs/plans/{task-id}.md` or the first commit message starting with
  `docs: plan for`).
- `git diff main...HEAD` — the cumulative diff.
- The test output from `/verify-acceptance` (passed in via env or
  re-derived by running the test plan commands again).

## Procedure

1. **Resolve task descriptor.**
   - Read `.claude/state/in-flight.json` for the current lane.
   - Extract task ID, branch, started_at.

2. **Find the plan.**
   - First commit on the branch is `docs: plan for {task-id}`.
   - Pull it via `git show {sha}:docs/plans/{task-id}.md` (or whatever
     path the plan committed itself to).

3. **Build the PR body** by filling this template verbatim:

```markdown
## Summary
{One or two sentences. What this PR delivers, who benefits.}

## What changed
- **Backend**: {bullets by module}
- **iOS**: {bullets by view/manager}
- **Schema/Infra**: {migrations, Terraform, AppConfig keys}
- **Tests**: {N new unit tests, M new integration tests}

## Why
{Quote the CLAUDE.md section or backlog ID this satisfies.}

## Test plan
- [x] `cd backend && python3 -m pytest -q` → {N passed}
- [x] `xcodebuild ... iPhone 17 build` → BUILD SUCCEEDED
- [x] `xcodebuild ... iPad Pro 11-inch (M4) build` → BUILD SUCCEEDED
- [x] `docker compose up && curl localhost:8080/health` → 200
- [x] {Each AC command + observed result}

## Security checklist
- [{tick if proved}] **Descriptive mode**: every new AI prompt enforces "describe, don't interpret/diagnose"
- [{tick if proved}] **No PHI in logs/errors/responses**
- [{tick if proved}] **AI calls via provider registry**
- [{tick if proved}] **Masking proof preserved** on every frame upload (P0-02)
- [{tick if proved}] **Audit log append-only** — no UPDATE/DELETE on audit rows
- [{tick if proved}] **Secrets via Secrets Manager**
- [{tick if proved}] **Consent gate intact** — recording requires `consent_confirmed`
- [{tick if proved}] **iOS Keychain only for voice embedding**
- [{tick if proved}] **Stage 1 < 30s / Stage 2 < 5min SLA** within budget
- [{tick if proved}] **Fail-closed masking (P0-01)** — no raw-byte fallback

## Out of scope
{Verbatim from the plan.}

## Deferred concerns
{P2/P3 simplify findings not fixed here. Link follow-up tickets.}

## Backlog
- Closes Linear AUR-{ticket}
- Backlog item: {task-id}

🤖 Opened by Aurion autonomous loop · Plan commit: {sha}
```

4. **Auto-prove security checkboxes.**

For each checkbox, run the corresponding proof and tick `[x]` if it passes,
leave `[ ]` if it fails or is ambiguous. Add a `→ {evidence}` annotation
on ticked boxes so the human can audit:

| Checkbox | Proof |
|---|---|
| Descriptive mode | `git diff main...HEAD -- '**/prompts/*'` returns no diff, OR the diff contains the descriptive-mode boilerplate from CLAUDE.md §"System Prompts" verbatim. |
| No PHI in logs | `git diff main...HEAD | grep -E '(logger\\.(info|debug|warning|error)\|print\\(\|raise.*Exception\\(.*).*(name\|mrn\|dob\|email)'` returns no hits. |
| Provider registry | `git diff main...HEAD | grep -E '(openai\\.|anthropic\\.|google\\.generativeai)\\b' | grep -v 'providers/'` returns no hits — no direct calls outside the registry. |
| Masking proof | Any new `POST /frames` or `POST /screen` route uses `MaskingProof` from `app.core.types`. `git diff` shows the import + usage. |
| Audit append-only | `git diff main...HEAD | grep -E '(UPDATE\|DELETE).*audit'` returns no hits. |
| Secrets via Secrets Manager | `git diff main...HEAD | grep -E '(API_KEY\|SECRET_KEY).*=.*["\\']'` returns no hardcoded keys. |
| Consent gate | If `git diff` touches recording paths, they reference `consent_confirmed` audit check. Hard to auto-prove → leave unticked unless trivially obvious. |
| Keychain only | If iOS diff touches voice embedding, check it stays in `KeychainHelper`. Leave unticked if unsure. |
| SLA budget | If touching hot paths, plan must include latency measurement. Tick only if measurement was performed and reported in test plan. |
| Fail-closed masking | Any new upload path checks `MaskingResult.success` before sending bytes. |

If you can't auto-prove a checkbox cleanly, **leave it unticked**. Honest
unticked is better than a falsely-ticked box that the auto-merge gate
will trust.

5. **Replace placeholders.**
   - `{N passed}`, `{sha}`, `{ticket}`, `{task-id}` filled from the
     context.
   - `{bullets by module}` derived from `git diff --name-only main...HEAD`
     grouped by top-level directory.

6. **Write the body to a tempfile and create the PR.**

```bash
gh pr create \
  --title "{task-id}: {short description}" \
  --body-file /tmp/aurion-pr-body-{task-id}.md \
  --base main \
  --head {branch}
```

7. **Update in-flight.json.**
   - Read the PR number from `gh pr create` output (it prints the URL on
     stdout).
   - Set `{lane}.pr` to the PR number.
   - Write back atomically.

8. **Post to Linear.**
   - Find the parent Linear issue from the plan (looks for `Linear: AUR-*`).
   - Comment on it: "PR opened: #{pr-number}. {short summary}."

9. **Return.**
   - Return the PR URL so the caller (`/await-ci`) knows what to poll.

## Refusals

- Do not open a PR if `/verify-acceptance` has not run cleanly. Check
  for a `.claude/state/verify-receipt-{task-id}.json` file (written by
  `/verify-acceptance`) and refuse if absent or stale.
- Do not open a PR against `main` from a branch that isn't named
  `lane-{backend,ios}/...`. Surface as ALERT.
- Do not tick a security checkbox you didn't prove. The PR template's
  honesty is the whole point.
- Do not push to the branch from this skill — assume the previous skills
  already pushed.

## Failure modes

| Failure | Response |
|---|---|
| `gh pr create` fails (auth, rate limit) | Retry once after 60s. Then ALERT to `alerts.md` and return error. |
| Branch already has an open PR | Use `gh pr edit` to update the body instead. |
| Plan file missing on branch | Refuse — the plan-commit gate was bypassed. ALERT. |
| Diff is empty | Refuse — nothing to merge. ALERT. |

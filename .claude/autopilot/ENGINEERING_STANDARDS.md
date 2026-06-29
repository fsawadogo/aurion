# Autopilot — engineering standards (the merge bar)

A code-writing or code-reviewing loop's change satisfies **all** of these, or it
**escalates to human review** (PR labelled `needs-human`) instead of auto-merging.
This is the same bar `AURION-CODING-WORKFLOW.md` §6c sets — Autopilot enforces it.

## Hard gates (a "no" = escalate, never merge)
1. **Green build.** Backend `pytest tests/unit` + `ruff check` pass; iOS change → both iPhone + iPad `xcodebuild` succeed; web change → `npm run build` passes. Never merge red.
2. **Regression test.** Every fix ships a test that fails before the change and passes after. No test ⇒ escalate.
3. **Minimal diff.** One finding = one branch = one PR, smallest change that fixes it. No drive-by refactors.
4. **Protected paths.** If the diff touches any `policy.json:protected_paths`, or the finding hits a `domain_sensitive_keywords` topic ⇒ escalate, regardless of autonomy level.
5. **Descriptive-mode / grounding.** No new AI prompt may add ungrounded interpretation/diagnosis; grounded synthesis stays cited + behind its flag (CLAUDE.md). Any prompt change ⇒ protected ⇒ escalate.
6. **No PHI** in logs / errors / API responses / S3 keys; **audit log append-only**; **fail-closed masking**; secrets only via Secrets Manager. A change weakening any of these ⇒ escalate.

## Quality principles (a reviewer-style check; clear violation ⇒ escalate)
- **DRY** — reuse existing helpers (`get_session_or_404`, `write_audit`, `get_config`, `get_registry`, `utcnow`, `MultipartBuilder`, `assemble_prompt`, …) before adding a third copy of a pattern.
- **SRP** — route handlers do HTTP-boundary work only; business logic in `app/modules/*`; SwiftUI views are presentation-only.
- **OCP** — extend via the provider registry / enum / template JSON, not `if provider == ...` branches.
- **LSP** — every provider returns the same schema; outputs interchangeable at the type boundary.
- **ISP / DIP** — narrow FastAPI dependencies; registry/audit/clock via injected helpers, never concrete instantiation.
- **KISS / YAGNI** — solve the actual finding, not a hypothetical; no speculative abstraction.
- **Clean Code** — names read like the surrounding code; comment density matches the file; no dead code.

## Style
Match the file you're editing (its idioms, naming, comment density). Backend = type hints + Pydantic + async; Swift = the project's `Theme.swift` tokens + EN/FR string parity; web = the existing component + i18n patterns.

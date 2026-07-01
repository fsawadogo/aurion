# Plan — #606 Hardening (scope-fidelity follow-ups)

## Task
606 — Two of the three hardening items from the MVP scope audit. (NURSE role **deferred** → issue #615 by decision on 2026-07-01.)

## Why
Close latent scope-fidelity gaps surfaced by the audit vs Aurion_MVP_Scope_Definition.pdf:
- "Review & Approval: all CONFLICTs resolved before approval" was enforced client-side + at the HTTP route, but the **service** invariant wasn't self-enforcing.
- "Audit Log Viewer: 7-year retention" was policy text, not a code/infra-level guarantee.

## Approach
1. **Server-side conflict gate** — move the "is this an open conflict" rule into the note_gen domain and enforce it inside `approve_note`, so approval refuses to sign off over unresolved Stage 2 CONFLICTS regardless of caller (the `/approve` route already pre-checks; the `video_import` auto-approve path calls the service directly).
   - `note_gen/service.py`: add `UnresolvedConflictError`, `is_unresolved_conflict_claim(claim)`, `unresolved_conflict_claim_ids(note)`; guard `approve_note` (check before flipping `is_approved`).
   - `api/v1/notes.py`: import the shared predicate, make the route's `_is_unresolved_conflict` delegate to it (DRY — single source of truth), and map `UnresolvedConflictError` → HTTP 409 at both `approve_note` call sites.
2. **7-year retention assertion** — the audit DynamoDB table has no TTL by design (unbounded retention ≥ 7yr); make that explicit + regression-guarded.
   - `infrastructure/dynamodb.tf`: explicit "NO `ttl` by design" comment referencing the 7-yr (2555-day) Quebec floor already codified in `logs_bucket.tf`.
   - `tests/unit/test_audit_retention.py`: parse the Terraform, assert the `audit_log` table declares no `ttl` block and documents the 7-yr floor.

## Acceptance criteria
- [ ] AC-1: `approve_note` raises `UnresolvedConflictError` on an open conflict claim and does NOT flip `is_approved` — `test_approve_note_conflict_gate.py::test_approve_note_raises_on_unresolved_conflict`.
- [ ] AC-2: `approve_note` succeeds once conflicts are physician-edited / absent — same file, resolved + no-conflict cases.
- [ ] AC-3: The conflict predicate is shared (route delegates to `note_gen.is_unresolved_conflict_claim`) — no duplicated rule.
- [ ] AC-4: Both `/approve` and `/approve-stage1` map the error to 409 (not 500/404).
- [ ] AC-5: Audit table has no TTL — `test_audit_retention.py::test_audit_log_table_has_no_ttl`.
- [ ] AC-6: 7-yr floor documented at the table — `test_audit_retention.py::test_audit_log_retention_rationale_documented`.

## DRY / SOLID check
- Reuse: existing `_deserialize_note`, `note_repo.get_latest_version`, the route's `ConflictState`/`_summarize_conflicts` (now sourced from the shared predicate). New domain rule lives in the module (SRP), not the route.
- No new cross-cutting helper beyond the conflict predicate, which replaces a duplicated inline rule.

## Out of scope
NURSE role (→ #615). No change to conflict *resolution* flow, note versioning, or the client UI (already gated). No new audit events.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_approve_note_conflict_gate.py tests/unit/test_audit_retention.py -q`
2. Regression: `python3 -m pytest tests/unit/test_conflict_resolution.py tests/unit/test_note_detail.py tests/unit/test_note_edit.py -q`
3. `ruff check` the changed files; `python3 -c "import app.api.v1.notes"` imports clean.

## Security implications
- Strengthens a safety invariant (no sign-off over unresolved audio/video conflicts) at the service layer. `UnresolvedConflictError` carries only claim/section ids (no PHI). Audit retention change is infra-comment + test only. No new PHI paths, prompts, or audit events.

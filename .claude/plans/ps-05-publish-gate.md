## Task
ps-05 (#518, part of MVP #524) — publish + rollout + feature/role gate + audit.

## Why
The "share it" half of #524 and the last backend slice: publishing moves a
version into a cohort (self / role / all) so it takes effect via ps-02
resolution. Adds the feature flag that ships the whole Studio dark + the role
allowlist, and the audit trail for the consequential publish action. After this
the create→publish→takes-effect loop is curl-testable. Spec → R1/R7/R8.

## Approach
- AppConfig (`config/schema.py`): `feature_flags.prompt_studio_enabled` (bool,
  default False) + `prompt_studio_roles` (list[str], default ["ADMIN"]).
- `require_prompt_studio` dependency gating EVERY Studio route — flag on AND
  role in allowlist, else 403. Replaces the per-route `require_role(ADMIN)`.
- `POST /prompts/{id}/publish` {version_id, scope, target_role?}: validates the
  version belongs to the prompt; supersedes the prior active (job, scope,
  target) publication (stamp `superseded_at`, never delete); inserts the new
  one; audits `PROMPT_STUDIO_PUBLISHED` (provenance only).
- New audit event `PROMPT_STUDIO_PUBLISHED` + whitelist + locked-test entry.

## Acceptance criteria
- [ ] AC-1: publish ALL / SELF / ROLE → 201 with the right target; ROLE without
  target_role → 400; unknown version → 404.
- [ ] AC-2: re-publishing the same (job, scope, target) supersedes the prior
  active row — 1 active, history kept (`test_publish_supersedes_prior_active`).
- [ ] AC-3: `PROMPT_STUDIO_PUBLISHED` audited with ids + scope, never the prompt
  text (`test_publish_writes_audit_no_text`).
- [ ] AC-4: flag off → all Studio routes 403, even ADMIN
  (`test_disabled_flag_forbids_all`); role not in allowlist → 403.
- [ ] AC-5: ruff + tests pass; the locked `test_audit_events` accepts the new
  member; `test_config_schema` accepts the new flags.

## DRY / SOLID check
- **Reused**: `write_audit`, `get_config`, `get_current_user`, `utcnow`,
  `PublicationScope`, the integration test fixtures, the `_PROMPT_AUDIT_SESSION_ID`
  sentinel convention from `me_prompts`.
- **OCP**: a new scope is `PublicationScope`-driven; widening the surface to a
  new role is an AppConfig list edit, no code change.

## Out of scope
Web UI (ps-06), the testing half (ps-04 / ps-07), the staged self→role→all
promote UI, per-specialty targeting, archive/unpublish.

## Test plan (executable)
1. `ruff check` on the touched files.
2. `pytest tests/integration/test_prompt_studio_api.py tests/unit/test_audit_events.py tests/unit/test_config_schema.py -q` (Postgres :5434).

## Security implications
Ships DARK — `prompt_studio_enabled` defaults False, so every Studio route 403s
until an operator flips it. The gate is the single allowlist for who may move a
global prompt. Publishing is audited (provenance only — actor / job / version_no
/ scope / target_role — never the text). The published text already passed the
descriptive-mode gate at create/save (ps-03); resolution (ps-02) sends it only
for clinicians without a personal override.

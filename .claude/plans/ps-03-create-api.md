## Task
ps-03 (#516, part of MVP #524) — Prompt Studio authoring API: create/upload a
prompt from scratch + save versions.

## Why
The "author or upload a prompt from scratch" half of #524. Gives the web UI
(ps-06) endpoints to create a prompt, save edits as versions, and list the
library — all behind the descriptive-mode safety gate. Spec:
`docs/plans/prompt-studio-spec.md` → R2/R3/R4. Builds on ps-01 models.

## Approach
New ADMIN-only module `app/api/v1/admin/prompt_studio.py` mounted at
`/api/v1/admin/prompt-studio`:
- `GET /jobs` — registry jobs + their live default text (for "start from current").
- `GET /prompts` — library (authored prompts by job + latest version, one grouped query).
- `GET /prompts/{id}` — prompt + version history.
- `POST /prompts` — create prompt + v1.
- `POST /prompts/{id}/versions` — append a new version (monotonic).
Every write runs `validate_user_prompt` and returns the SAME 400 detail shape
(`message`/`code`/`matched_phrase`/`missing_anchor_group`) as `me_prompts.py`,
so the web parses both identically. Gated with the existing
`require_role(UserRole.ADMIN)` dependency.

**Deliberately deferred to ps-05:** publish/rollout, the `prompt_studio_enabled`
feature flag + configurable role allowlist (this slice is ADMIN-only), and
audit events. Authoring is inert until a version is published.

## Acceptance criteria
- [ ] AC-1: ADMIN creates a prompt for a valid job → 201 with v1; verified by
  `test_create_prompt_happy_path`.
- [ ] AC-2: unknown `job_id` → 404 (`test_create_rejects_unknown_job`).
- [ ] AC-3: text failing the descriptive-mode gate → 400 with the specific
  code (`test_create_uploaded_text_is_validated_for_descriptive_mode`,
  `test_create_rejects_banned_phrase`).
- [ ] AC-4: saving a version appends monotonically; detail lists [1, 2]
  (`test_save_version_appends_monotonically`); unknown prompt → 404.
- [ ] AC-5: library lists the created prompt with its latest version;
  `/jobs` exposes the registry default text.
- [ ] AC-6: non-ADMIN roles → 403 (`test_non_admin_forbidden`).
- [ ] AC-7: `ruff check` + `pytest tests/integration/test_prompt_studio_api.py` pass.

## DRY / SOLID check
- **Existing helpers reused**: `require_role(UserRole.ADMIN)`, `get_db`,
  `validate_user_prompt` + `ValidationCode` + the 400 detail shape from
  `me_prompts.py`, the admin-router registration pattern, the integration test
  fixtures from `test_prompt_overrides.py`.
- **New helper introduced?**: small local `_validated` / `_job_or_404` /
  `_prompt_or_404` — module-private, no duplication of an existing helper.
- **SRP**: route handlers stay HTTP-only; no business logic beyond
  validate + persist.

## Out of scope
Publish/rollout + feature flag + audit (ps-05), resolution (ps-02, separate PR),
web UI (ps-06), testing half (ps-04/ps-07). No archive/delete endpoints yet.

## Test plan (executable)
1. `ruff check app/api/v1/admin/prompt_studio.py app/api/v1/admin/__init__.py tests/integration/test_prompt_studio_api.py`
2. `pytest tests/integration/test_prompt_studio_api.py -q` (Postgres :5434, at head 0042)

## Security implications
ADMIN-only. Every saved text passes the descriptive-mode safety gate before any
row is written — a prompt that strips the boundary can't be stored. No PHI; the
prompt text is sensitive but not patient data and is never logged. No audit
events in this slice (publish writes those in ps-05); authoring is inert until
published, so the auditable state change is the publish, not the draft.

# Plan — eval-rerun-1 (#590): per-user prompt-testing + regenerate-note

## Task
#590. Let SPECIFIC, admin-assignable users re-run note generation on an
already-uploaded encounter with a different prompt/template — no re-upload, no
re-transcribe. Phase 1 = audio/Stage-1 from the stored transcript.

## Why
The transcript is already persisted (`TranscriptModel`) and
`generate_stage1_note(transcript, …, template_key, custom_template_id)` already
takes them as inputs — so "re-run with a different template/prompt" is a gated
call on stored data. This is the eval loop for tuning the per-visit-type
medico-legal prompts (the audit's #1 priority). Templates carry their AI
instructions (tpl-01), so "different prompt" = "different template".

## Approach (simplest maintainable; lane-full, ONE PR)
**Gate = one per-user boolean `prompt_testing_enabled`**, mirroring the existing
`is_active` / `mfa_required` columns. Orthogonal to role; admin toggles it per
user in the EXISTING Users admin. No new role, no capability engine.

### Backend
- `core/models.py` `UserModel`: add `prompt_testing_enabled: bool` (Boolean,
  `server_default="false"`), mirroring `mfa_required`.
- Migration **0045** (← 0044): `op.add_column("users", Boolean, server_default false)`,
  mirroring `0039_user_mfa_required`. (No baseline edit needed — plain column.)
- `admin/_shared.py`: add the field to `UpdateUserRequest`, `UserResponse`, and
  `user_to_response()`. `admin/users.py` PATCH passes it to `users_repo.update_user`.
- `auth/users_repository.py` `update_user`: accept + persist the field.
- `auth.py` `/auth/me` (`CurrentUserResponse`): expose `prompt_testing_enabled`
  so the web can gate the affordance.
- **Endpoint** `POST /api/v1/sessions/{session_id}/regenerate-note` (in
  `sessions.py`, role-agnostic — `Depends(get_current_user)`):
  - owner-scoped via `get_owned_session_or_404` / `assert_owner` (works for a
    clinician's own upload AND an eval/admin uploader's own session);
  - **gate**: re-fetch the user row (`db.get(UserModel, user.user_id)`) →
    403 unless `prompt_testing_enabled` (mirrors `_ensure_active` precedent;
    `CurrentUser` doesn't carry the flag);
  - load `TranscriptModel` → deserialize to `Transcript` (404 if none);
  - body = `{ template_key?, custom_template_id? }` (a template selector);
  - call `generate_stage1_note(transcript, specialty=session.specialty, …,
    template_key, custom_template_id)` — reuses template resolution + prompt
    cascade + auto-versions a new `NoteVersionModel`;
  - audit `NOTE_REGENERATED` (new count-only event) with the template selector;
  - return the new note version (reuse the existing note response shape).

### Web
- `types/index.ts`: add `prompt_testing_enabled?: boolean` to `UpdateUserPayload`
  and `CurrentUser`.
- `app/users/page.tsx`: a per-user "Prompt testing" toggle (ADMIN-only page)
  mirroring `handleSetMfaRequired` → `updateUser(id, {prompt_testing_enabled})`.
- `lib/api.ts`: `regenerateNote(sessionId, {template_key?, custom_template_id?})`.
- `app/portal/notes/[id]/NoteReviewClient.tsx`: a "Regenerate with template…"
  control (a template `<select>` + button) shown ONLY when
  `me.prompt_testing_enabled`; on submit → `regenerateNote` → reload the note.

## Acceptance criteria
- [ ] AC-1: `users.prompt_testing_enabled` added (migration 0045); settable via PATCH /admin/users/{id} (ADMIN); returned in the users list + `/auth/me`.
- [ ] AC-2: `POST /sessions/{id}/regenerate-note` → 403 unless the caller has the flag; owner-scoped (404 on a non-owned/absent session or missing transcript); reuses the stored transcript; creates + returns a new note version; never re-transcribes.
- [ ] AC-3: regenerate honours a `template_key` / `custom_template_id` override (different template → different note).
- [ ] AC-4: Users admin shows the per-user toggle; the note page shows the Regenerate control only to granted users.
- [ ] AC-5: backend tests (gate allow/deny, owner-scope, reuses transcript, template override) + web tests (toggle, gated affordance); ruff + eslint + tsc + full suites green.

## DRY / SOLID
- Reuses `generate_stage1_note` (template resolution + prompt cascade + versioning) — NO new note-gen path. Mirrors the existing per-user-boolean plumbing end-to-end (`mfa_required`) and the `_ensure_active` re-fetch pattern for the gate. New = one column + one endpoint + one toggle + one button.
- SRP: route does HTTP/auth/owner/gate + delegates to `generate_stage1_note`. OCP: template override flows through the existing resolver, no branching.

## Out of scope (Phase 2)
- Video/Stage-2 re-runs (wire `eval_mode` retention so frames/video aren't purged; optionally persist captions).
- Side-by-side A/B diff UI (fold into Prompt Studio ps-04 dry-run).
- Raw free-text prompt override (use templates, which carry instructions).
- Cross-user eval re-run (owner-scoped only for now).

## Test plan (executable)
1. `cd backend && .venv/Scripts/python -m pytest tests/unit/test_regenerate_note.py tests/unit/test_users_admin*.py -q` (new + existing)
2. `ruff check` the touched backend files
3. `cd web && npx eslint <touched> && npx tsc --noEmit && npx vitest run`
4. Live: grant a user the flag in Users admin → open an uploaded encounter → Regenerate with a different template → new note version appears (no re-upload).

## Security implications
- New per-user capability; assignment stays ADMIN-only (PATCH gate unchanged).
- Regenerate is gated (flag) + owner-scoped (own session only). Reuses the
  stored transcript + the descriptive-mode prompt cascade — no new PHI surface,
  no prompt-safety bypass. Audit event is count-only (no PHI). Gate re-fetches
  the user row (1 query) rather than trusting a stale token claim.

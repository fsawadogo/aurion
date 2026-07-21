# Plan — TE-4d

## Task

Make the web **upload-video** flow resolve its template through the clinician's **visit-context → template mapping** — the same path iOS uses — instead of only a flat "pick a custom template by name." And take the specialty from the clinician's profile rather than a per-upload picker.

## Why

Uzziel, 2026-07-20: he wants to test "the whole flow" — pick a visit context (e.g. follow-up), which applies the mapped template — the way Marie experiences it on iPad. Audit (two agents, quote-backed) found:

- The web upload flow sends only `specialty` + `encounter_type` + a direct `custom_template_id`, and the backend `create_import_session` **never calls `resolve_context_template_key`** — so it bypasses the clinician/org visit-type→template mapping entirely.
- That mapping already exists and works (Profile page + Templates "Visit Types" tab), resolved server-side by `resolve_context_template_key` (precedence: chosen context pin → clinician default → org default → specialty default).
- iOS's `POST /sessions` calls that resolver; the web upload's `POST /me/video-imports` does not. **The two paths are separate endpoints** that share only `create_session` (row builder) and the resolver — both of which already accept these fields.
- The upload form's own `specialty` picker contradicts Uzziel's rule that specialty is a profile property (`PhysicianProfile.primary_specialty`).

## The iOS-safety invariant (the whole reason this is safe)

> iOS talks to `/sessions`; upload talks to `/me/video-imports`. This slice changes **only** the upload endpoint and the web upload form, and it **reuses `resolve_context_template_key` unchanged** — never touching its signature or behaviour. iOS keeps running the identical code path.

The review will verify this invariant explicitly. Any change to the shared resolver or `create_session` signature would break it and is out of scope.

## Approach

### Backend — `api/v1/video_import.py`

1. `CreateVideoImportRequest`: add `context_id: Optional[str] = None`. (`consultation_type` + `encounter_context` already exist.)
2. `create_import_session`: precedence, keeping the direct picker as an override (Uzziel: "keep both"):
   - explicit `body.custom_template_id` present → resolve ownership as today (override wins);
   - else if `context_id` or `consultation_type` present → call `resolve_context_template_key(...)` exactly as `sessions.py` does, taking the resolved `(template_key, custom_template_id)`;
   - else → specialty default (both `None`), byte-identical to today.
   - Pass `context_id`, `template_key`, `custom_template_id` into `create_session` (it already accepts them).

### Web — `VideoImportClient.tsx` + `portal-api.ts`

3. Fetch the clinician profile (`getMyProfile`) → `primary_specialty`, `consultation_types`, `contexts_per_visit_type`.
4. **Remove the specialty `<select>`** — send `primary_specialty` from the profile. (Backend contract unchanged: `specialty` still travels, just sourced from the profile.)
5. Add a **visit-context picker**: a visit-type select (`consultation_types`) → a context select (the visit type's contexts). Sends `consultation_type` + `context_id`. "No specific context" clears both → specialty default.
6. Keep the custom-template picker as an explicit **override**.
7. `VideoImportCreateBody`: add `consultation_type?`, `context_id?`.

## Acceptance criteria

- [ ] **AC-1 (backend):** with `context_id` set and no explicit `custom_template_id`, `create_import_session` calls `resolve_context_template_key` and snapshots its result onto the session — `test_te4d_video_import_visit_context.py::resolves_template_from_context`
- [ ] **AC-2 (backend):** an explicit `custom_template_id` overrides the visit-context resolution — `::explicit_custom_template_overrides_context`
- [ ] **AC-3 (backend):** neither context nor custom template → specialty default, byte-identical to today (no resolver call) — `::no_context_is_byte_identical`
- [ ] **AC-4 (backend, iOS-safety):** the change touches only `video_import.py`; `resolve_context_template_key` and `create_session` signatures are unchanged — asserted by the review + `git diff` scope
- [ ] **AC-5 (web):** the form sends `consultation_type` + `context_id` from the visit-context picker and `specialty` from the profile (no specialty picker) — `VideoImportVisitContext.spec.tsx`
- [ ] **AC-6 (web):** the custom-template override still sends `custom_template_id` — `::template override still works`
- [ ] **AC-7:** full `tests/unit/` + `vitest` green; ruff + lint + build clean; `git diff --stat main...HEAD -- ios/` empty

## Out of scope

- **TE-4e** — removing the 8 specialty templates from the note-review "Change template" dropdown + `VisitTypeContextsEditor` (scope locked separately: profile-default everywhere).
- Any change to `resolve_context_template_key`, `create_session`, or the iOS `/sessions` path.
- The patient-identifier 500 (KMS) — separate chip.

## Test plan

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_te4d_video_import_visit_context.py -v`
2. `pytest tests/unit/ -q` green; `ruff check app/ tests/` clean
3. `cd web && npx vitest run` green; `npm run lint`; `npm run build`
4. Mutation-test each backend AC
5. `git diff --stat main...HEAD -- ios/` → empty

## Security / safety

- **iOS untouched** — separate endpoint, shared resolver reused read-only (the invariant above).
- **No new PHI** — visit-context ids and template ids are config, not patient data.
- **Descriptive mode / template engine flag** unaffected — this is about *which* template resolves, not what the pipeline does with it.
- **Admin import surface** (`create_import_session` also backs admin/eval) inherits the same behaviour; an admin run with no context is byte-identical to today (AC-3).

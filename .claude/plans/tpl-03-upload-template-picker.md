# tpl-03 — upload-flow template picker (step 2)

Closes the upload-and-test loop: lets a clinician **apply a chosen custom
template** (its structure + AI instructions from tpl-01/02) to an uploaded
encounter video, then read the result in the existing clean note viewer.

## Change

### Backend — `app/api/v1/video_import.py`
- `CreateVideoImportRequest` gains `custom_template_id: Optional[str] = None`.
- `create_import_session`: when set, validate it is **owned by the clinician**
  (`get_owned`, the same ownership-scoped check the live session-create uses);
  **404** on unknown/foreign id (the picker only lists owned templates, so a miss
  means a stale pick or tampering). Pass the resolved id into `create_session`,
  which already accepts `custom_template_id`. The whole upload then flows through
  the same `generate_stage1_note` path, so the template's structure + instructions
  apply exactly as for a live session.

### Web — `VideoImportClient.tsx` + `portal-api.ts`
- `VideoImportCreateBody.custom_template_id?: string | null` (shared by the
  clinician + admin create calls).
- Clinician-only: fetch `listMyCustomTemplates()` and render an optional
  "Note template" picker (default = by specialty); send the chosen id. Admin/eval
  uploads keep the specialty default (no picker).
- i18n: `VideoImport.form.template` / `…templateDefault` (en + fr).

## Tests
- Backend (unit): owned `custom_template_id` is forwarded to `create_session`;
  an unowned id → 404 and no session created.
- ruff + 1536 unit green; eslint clean; web typecheck clean (changed files);
  i18n en/fr parity green.

## After this lands — the loop works
With `video_import_enabled` on: create a template with AI instructions
(tpl-02) → Upload Video, pick that template → read the note in
`/portal/notes/[id]`.

## Out of scope
- iOS in-app picker (step 3) — Path 2 works today via the profile context binding.
- The full Example/Structure clean redesign.

## Verify → self-reviewed (ownership gate tested both ways) → PR.

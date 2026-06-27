# tpl-04 — shared / org templates (admin creates → clinicians use)

The last conceptual piece of "admins author → clinicians use." An ADMIN
authors a note template marked `is_shared=true`; it appears **read-only** in
every clinician's library + the upload / visit picker, and resolves at note
generation. Reuses the existing `is_shared` column + `list_for_owner(
include_shared=True)` (no migration).

## The trap this fixes (found in review)
A shared template is owned by the admin. Both note-gen **selection** sites used
owner-scoped `get_owned`, so a clinician would *see* a shared template but get a
404 (upload) / silent fallback (session) when they *picked* it. PR1 adds
`get_owned_or_shared` and swaps both sites — without it the feature looks done but
no-ops at generation.

## PR1 — backend (this PR)
- **`custom_templates/service.py`**
  - `create_for_owner(..., *, is_shared=False)` — parametrized (default keeps every
    existing caller); admin passes `True`.
  - `get_owned_or_shared(id, owner, db)` — owned OR shared. For clinician READ +
    the selection paths. Narrower than `get_by_id` (won't leak another owner's
    PRIVATE template). Edit/delete stay on `get_owned`.
  - `get_shared(id, db)` + `list_shared(db)` — admin manage/delete (is_shared only).
- **Selection swap (the trap fix):** `session/service.py` `_resolve_custom_template_ref`
  and `video_import.py` upload picker → `get_owned_or_shared`.
- **`admin/shared_templates.py`** (new, ADMIN-only): POST/GET/DELETE `/admin/
  shared-templates`. Reuses `create_for_owner(is_shared=True)` (so the
  descriptive-mode gate on any AI instructions, tpl-01, still runs),
  `list_shared`, `get_shared`+`delete_owned`. Audits `CUSTOM_TEMPLATE_CREATED/
  DELETED`. Registered in `admin/__init__.py`.

## Tests
- Service: `create_for_owner(is_shared=True)` marks the row; default stays False.
- Admin endpoint: create forwards `is_shared=True` + audits + commits; bad template → 400; delete on a non-shared id → 404, no delete.
- **Integration (security WHERE):** `get_owned_or_shared` resolves a shared template for a non-owner, returns None for another owner's PRIVATE template, and resolves an owned one.
- Updated `_resolve_custom_template_ref` + video-import tests for the swap.
- ruff + 1540 unit + integration green.

## Display side — already wired (so PR2 is small)
`list_for_owner(include_shared=True)` already returns shared rows; the list page
renders a "Shared" badge + owner-gated Delete; the type carries is_shared+owner_id.
So shared templates already appear in the clinician library AND the upload picker.

## PR2 — web (next)
Admin "Shared templates" manage page (create via TemplateSectionEditor, list,
delete) + nav. Clinician side is near-zero (display already works).

## Verify → `/code-review` (security WHERE) → PR.

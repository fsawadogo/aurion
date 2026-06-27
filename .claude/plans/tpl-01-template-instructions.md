# tpl-01 — a template carries its note-gen instructions (backend)

Step 1 of the upload-and-test loop. Lets a note template hold its own AI
instructions (the prompt), not just its section structure — so picking a
template selects the whole "recipe." Foundation for testing templates via
video-upload (step 2) and iOS record.

## Change

- **`core/types.py`** — `Template.system_prompt: Optional[str] = None`. Stored in
  the custom-template `content` JSON blob → **no migration**; built-in templates
  carry `None` unless populated.
- **`prompts/assembly.py`** — new `template_prompt` tier in `assemble_prompt`:
  **personal override → template prompt → admin publication → registry default**.
  Threaded through `assemble_prompt_for_session` (and its missing-session
  fallbacks honor it too).
- **`note_gen/service.py`** — pass `template_prompt=template.system_prompt` into
  the resolver. The template is already resolved (`_resolve_stage1_template`)
  before the prompt is assembled, so it's in scope; no ordering change.
- **`custom_templates/service.py`** — when a template carries instructions,
  validate them with `validate_user_prompt` (the SAME descriptive-mode gate as
  personal overrides + Prompt Studio) on every write. Empty/whitespace = no
  instructions (structure only).

Both entry points (iOS live session + web video-upload) already share
`generate_stage1_note`, so this applies uniformly to both once template
selection is exposed at each front door (steps 2–3).

## Tests
- Resolution precedence (integration, real PG): template prompt used when no
  override; template beats publication; personal override beats template; empty
  falls through to publication/default.
- Validation (unit): descriptive prompt accepted; missing-anchor prompt rejected
  at write; no-instructions template unaffected.
- ruff clean; **1533 unit** + prompt-resolution integration green.

## Not in this PR (later steps)
- Web editor "AI instructions" field + the clean Example/Structure toggle.
- Upload-flow template picker (step 2) + iOS in-app picker (step 3).
- Admin System-Templates instruction field (so an admin-set specialty template's
  instructions reach every clinician using it).

## Verify → `/simplify` → `/code-review` → PR.

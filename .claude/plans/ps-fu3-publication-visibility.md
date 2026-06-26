# ps-fu3 — clinician visibility of the active published prompt

Publishing a Studio prompt was **silent**: it swaps the system prompt note-gen
uses for the cohort, but a clinician had no way to SEE that an admin shared a
prompt with them. This adds a read-only banner on the **AI Prompts** page
(`/portal/prompts`) showing the active admin publication per job.

## Design

Extend the existing `GET /me/prompts` response with an optional
`admin_publication` field — **no new endpoint**. Resolve it the SAME way
note-gen resolves (`SELF → ROLE → ALL`), reusing the precedence selector so the
banner can never disagree with what actually drives notes.

Key difference from note-gen: the visibility resolver does **NOT** short-circuit
on a personal override. note-gen returns the override and never looks at
publications; the banner must still show the publication so the UI can tell the
clinician their own prompt is *shadowing* it.

### Backend
- `assembly.py`:
  - Extract `_select_published_index(keys, owner_id, role_value)` — the single
    home of the PS-02 precedence rule. `_select_published` (note-gen text path)
    becomes a thin wrapper, so behavior is unchanged (existing unit tests hold).
  - Add `PublishedPromptMeta` (NamedTuple) + `get_active_publications_for(db,
    owner_id, prompt_ids) -> dict[job_id, meta]` — one role lookup + one
    publications query for all jobs (no N+1), returns display metadata
    (name, version_no, scope, target_role, published_at). Does NOT filter on a
    personal override (visibility, not runtime).
- `me_prompts.py`: `AdminPublicationResponse` model + `admin_publication` field
  on `PromptResponse`; `_serialize` takes the optional publication; list / patch
  / delete all resolve + attach it (byte-identical shapes preserved).

### Web
- `AdminPublicationMeta` type + `admin_publication?` on `AIPrompt`.
- `PromptCard`: a banner at the top of the card body — sky "this is the prompt
  your notes use" when active; amber "your own prompt takes priority" when
  `is_overridden` (shadowed).
- i18n `AIPrompts.adminPublication.{active,shadowed}` in en + fr (parity).

## Verify
- Backend: ruff; the 4 new resolver integration tests (real PG); the me_prompts
  schema-lock test updated for the new key; full unit + prompt integration green.
- Web: eslint; vitest incl. a new `PromptCard.spec` (no-banner / active /
  shadowed) + the en↔fr parity test.
- `/simplify` → `/code-review` → PR.

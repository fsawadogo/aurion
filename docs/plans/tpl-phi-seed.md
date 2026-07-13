# Plan — tpl-phi-seed: PHI-safe template-authoring seeds

## Task
tpl-phi-seed — the document a clinician pastes/uploads to seed a template
authoring session is used for extraction but never persisted verbatim.

## Why
`template_authoring.upload_template_document` builds a seed user turn containing
the **full document text** and persists it in `TemplateAuthoringSessionModel.messages_json`
(`_encode_messages(history)`). A clinician may paste a filled-in note, so the
stored history can carry patient specifics — a PHI leak into the DB row.
CLAUDE.md §Non-Negotiable Technical Rules: "PHI never in logs, errors, API
responses … or S3 keys." This closes the same class of leak for the authoring
message store, and is the foundation the upcoming `from-note` seed (a real
patient note) depends on.

## Approach
Extract a shared `_seed_authoring_session(owner_id, source_text, stored_placeholder, db)`
in `template_authoring/service.py`:
- Sends the **full** `source_text` to the LLM (prefixed with a generalize /
  strip-PHI extraction instruction) so structure extraction still works.
- Persists only `stored_placeholder` where the source turn would be — the row
  stays reconstructable ("a document was provided") without the content.
- `upload_template_document` becomes a thin caller that builds the placeholder
  and delegates. No route/schema/DB-migration change.

Files: `backend/app/modules/template_authoring/service.py` only (+ tests).

## Acceptance criteria
- [ ] AC-1: the full source reaches the LLM — verified by
  `test_upload_sends_full_source_to_llm` (sentinel present in captured messages).
- [ ] AC-2: the source is NOT in `messages_json`; the placeholder is — verified
  by `test_upload_redacts_source_from_stored_history`.
- [ ] AC-3: the generalize instruction reaches the LLM — verified by
  `test_upload_includes_generalize_instruction`.
- [ ] AC-4: extraction still yields a draft + active session — verified by
  `test_upload_still_extracts_draft` and the existing `test_template_authoring.py` suite.

## DRY / SOLID check
- **Existing helpers reused**: `_generate_with_validation_retry`,
  `_encode_messages`, `_BOOTSTRAP_MESSAGE`, `get_registry().get_note_provider()`,
  `TemplateAuthoringSessionModel`, `AuthoringReply` — all already in the module.
- **New helper introduced?**: yes — `_seed_authoring_session`. Justified: it is
  the SECOND caller of this exact seed-and-persist pattern (upload today,
  from-note next PR), and it is the seam where the redaction boundary lives.
- **iOS UI tasks only**: n/a (backend).

## Out of scope
- The `POST /me/template-authoring/from-note/{session_id}` endpoint, the
  `create_authoring_from_note` service fn, and `_note_to_text` — next PR
  (tpl-from-note), shipped behind the `template_authoring_chat` flag.
- The feature flag + web UI.

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/test_template_authoring_phi_safe_seed.py -v`
2. `cd backend && python -m pytest tests/unit/test_template_authoring.py -q` → still green (regression).
3. `ruff check app/modules/template_authoring/service.py`

## Security implications
Touches an AI-prompt seed + a DB text column. Net effect is a **reduction** in
PHI surface (source no longer persisted). No new PHI in logs/errors/responses.
Extraction instruction is structure-only — no interpretive/diagnostic language,
consistent with descriptive mode and the existing authoring system prompt. No
audit/consent/masking path touched.

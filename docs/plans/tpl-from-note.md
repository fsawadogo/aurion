# Plan — tpl-from-note: create a template from a past encounter's note

## Task
tpl-from-note — a clinician can seed the "Create with AI" template chat from one
of their own past notes: the note is reverse-engineered into a reusable template
structure they then refine via chat.

## Why
July 1 strategy meeting: Marie & Perry want to bring the notes they already write
and have Aurion turn them into templates ("from a past encounter"). Builds on the
now-hardened, PHI-safe `_seed_authoring_session` (#648). Ships DARK behind a flag
because dev = prod.

## Approach
- **Service** (`template_authoring/service.py`): `create_authoring_from_note(owner_id, note, db)`
  renders the note's populated sections to text (`_note_to_text`) and delegates to
  the existing `_seed_authoring_session` — so the note reaches the LLM for
  extraction but only a redacted placeholder + the fixed acknowledgment are
  persisted (inherited PHI-safety), and the extraction keeps structure only.
- **Endpoint** (`me.py`): `POST /me/template-authoring/from-note/{session_id}` —
  gated on the new flag, owner-scoped (`get_owned_session_or_404`), fetches the
  latest note (`get_latest_note`), calls the service, maps ValueError→400 /
  ProviderError→502.
- **Flag** (`config/schema.py`): `template_authoring_chat_enabled: bool = False`
  (org-level, DARK by default). The endpoint 403s while off.

Reuses: `_seed_authoring_session`, `get_owned_session_or_404`, `get_latest_note`,
`get_config`, `get_current_clinician`, `_to_authoring_response` — all existing.

## Acceptance criteria
- [ ] AC-1: from-note extracts a draft into an active session — `test_from_note_extracts_draft`.
- [ ] AC-2: note content reaches the LLM but is NOT persisted in messages_json — `test_from_note_redacts_note_content` (inherits the #648 boundary).
- [ ] AC-3: a note with no populated sections → 400/ValueError — `test_from_note_empty_note_raises`.
- [ ] AC-4: `_note_to_text` includes populated sections, skips empty ones — `test_note_to_text_skips_empty_sections`.
- [ ] AC-5: endpoint 403s when the flag is off (verified by the flag gate; existing config/feature-flag suites stay green).

## DRY / SOLID check
- **Existing helpers reused**: `_seed_authoring_session` (the redaction seam from #648 — now its 2nd caller, justifying the earlier extraction), `get_owned_session_or_404`, `get_latest_note`, `get_config().feature_flags` gate (mirrors `me_measurements.py`), `_to_authoring_response`.
- **New helper introduced?**: `_note_to_text` — single-purpose note→text; no existing equivalent (export serializers build DOCX, not extraction text).
- **iOS UI tasks only**: n/a.

## Out of scope
- Per-role / per-user flag targeting (needs a `UserModel` column + admin API) — follow-up; org-level bool is enough to ship DARK for the pilot.
- Web UI (Templates "Create with AI" chat) — later PR.
- Bringing the pre-existing authoring endpoints (start/continue/finalize/upload) under the flag — they stay as-is to avoid disabling a live (UI-less) surface; a later PR can gate the whole surface deliberately.

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/test_template_authoring_from_note.py -v`
2. `cd backend && python -m pytest tests/unit/test_template_authoring.py tests/unit/test_template_authoring_phi_safe_seed.py -q` → green (regression)
3. `cd backend && python -m pytest tests/unit/test_feature_flags_admin.py -q` → green (flag added cleanly)
4. `ruff check app/modules/template_authoring/service.py app/api/v1/me.py app/modules/config/schema.py`

## Security implications
Reads a real patient note (PHI) and sends it to the note provider for extraction
— the same sanctioned data flow as note generation. PHI-safe persistence is
inherited from `_seed_authoring_session` (#648): note never stored verbatim.
Owner-scoped, flag-gated (DARK), descriptive/structure-only extraction. No new
PHI in logs/errors/responses; no audit/consent/masking path touched.

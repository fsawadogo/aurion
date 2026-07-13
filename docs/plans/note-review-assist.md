# Plan — note-review-assist: the "fix this note" chat backend

## Task
`POST /notes/{session_id}/assist` — a physician reviewing a note sends a
plain-language request ("shorten the HPI", "add that she's allergic to sulfa");
an LLM emits structured edit ops that are applied to the note and saved as a new
immutable version. Flag-gated DARK.

## Why
Build B of the approved plan (the second conversational surface). Marie & Perry
asked for a Heidi-style "fix this note" chat under the generated note. This PR is
the backend engine; the web chat bar is a follow-up. Client-agnostic contract so
iOS can reuse it later (mobile-ready).

## Approach (no provider-interface change)
- **New module `app/modules/note_review/`**: `system_prompt.py` (a grounded
  note-editor prompt) + `service.py`.
- **Structured output** via the established `generate_text` + fenced-JSON +
  validate-and-retry pattern (same as `orders`/`coding`/template authoring) — no
  new provider method. The model emits `{"action":"edit_note","message":...,"ops":[...]}`.
- **Ops**: `reword_claim` / `remove_claim` / `add_claim`. Applied onto
  `note.model_copy(deep=True)` mirroring the `resolve_conflict` invariants (stash
  `original_text` + set `physician_edited` on first edit), then
  `create_note_version(..., stats_trigger="note_review_assist")`.
- **Grounding (safety)**: an `add_claim` cites a real transcript `seg_id` when
  the content is in the transcript; otherwise it is recorded as `physician_edit`
  (`source_id=pedit_{section}`) — **a transcript citation is never fabricated**.
- **Stateless**: the current note IS the state, so each turn carries only the
  message — no server-side chat history → no PHI message store.
- **Endpoint** in `notes.py`: owner-scoped, state-guarded (AWAITING_REVIEW /
  REVIEW_COMPLETE, matching `edit_note`), flag-gated, reuses the
  `NOTE_VERSION_CREATED` audit event. A conversational reply → `applied=False`,
  no version.
- **Flag** `note_review_chat_enabled` wired through `FeatureFlagsConfig`,
  `appconfig.tf`, the admin `FeatureFlagsResponse` + builder, and the two flag
  test fixtures.

Reuses: `get_latest_note`, `create_note_version`, `assemble_prompt_for_session`,
the fenced-JSON pattern, `get_owned_session_or_404`, `_to_note_response`.

## Acceptance criteria
- [ ] AC-1: reword keeps provenance (`original_text` + `physician_edited`) — test.
- [ ] AC-2: add grounded → cited to the seg; add ungrounded → `physician_edit`, never a fabricated seg id — test.
- [ ] AC-3: remove drops the claim; unknown claim/section refs are skipped — test.
- [ ] AC-4: edits version the note; a conversational reply does not — test.
- [ ] AC-5: endpoint 403s when the flag is off; audits + commits when applied — test.
- [ ] AC-6: full backend unit suite + ruff green.

## Out of scope / follow-up
- Web chat bar under the note (refresh `NoteReviewClient.tsx`) — next PR (needs
  the portal flag exposed too).
- `add_section` op; multi-turn history / "undo".
- "Remember how I like it" style-learning bridge.
- iOS wiring (endpoint is mobile-ready).

## Test plan (executable)
1. `cd backend && python -m pytest tests/unit/test_note_review.py -v`
2. `cd backend && python -m pytest tests/unit/ -q` → all pass (flag completeness locks)
3. `ruff check app/modules/note_review/ app/api/v1/notes.py ...`

## Security implications
Reads the note + transcript (PHI) and sends them to the note provider for
editing — the same sanctioned flow as note generation. Nothing new is persisted
except the edited note version (append-only, same as `edit_note`). Grounding is
enforced server-side (never a fabricated citation). Owner-scoped, flag-gated
DARK, descriptive/edit-only (no AI-invented clinical content). No PHI in
logs/errors (validation errors summarized to loc+msg).

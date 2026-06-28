## Task
GS-6 (#548) — NoteClaim: allow multiple source anchors per claim (back-compat)

## Why
A synthesized A&P line (GS-1 grounded mode) often rests on SEVERAL findings, but a
claim can cite only one source today. Add an optional `additional_sources` list so
synthesis stays fully traceable. Back-compat + inert for descriptive claims (which
never populate it), so NOT flag-gated — it's a schema capability, not a behaviour.

## Approach
- `core/types.py`: add `ClaimSource` (source_id min_length 1, source_quote="") +
  `additional_sources: list[ClaimSource] = []` to NoteClaim + `all_source_ids` helper.
- `providers/note_gen/shared.py`: add OPTIONAL `additional_sources` array to the claim
  schema (NOT in `required` — descriptive output unchanged).
- Parsing flows through Pydantic model_validate → picks up the optional field; default
  keeps every existing claim/parse path identical.

## Acceptance criteria
- [ ] AC-1: NoteClaim with no additional_sources behaves exactly as today (back-compat) — test
- [ ] AC-2: NoteClaim round-trips additional_sources; `all_source_ids` returns primary + extras — test
- [ ] AC-3: ClaimSource rejects empty source_id (min_length 1) — test
- [ ] AC-4: claim schema lists additional_sources as OPTIONAL (not required) — test
- [ ] AC-5: existing note-gen / parse / critique tests stay green (no behaviour change)

## DRY / SOLID check
- **Reuse**: NoteClaim/NoteSection Pydantic, existing parse via model_validate. New ClaimSource mirrors the single-anchor pair (the THIRD anchor representation → extraction justified).

## Out of scope
- iOS tap-to-source multi-anchor rendering (iOS tolerates the optional field via Codable; richer UI is a follow-up). GS-2 examples (separate). Flipping any flag.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_multianchor_claim.py tests/unit/test_note_gen.py tests/unit/test_parse_empty_note.py -q`

## Security implications
Additive schema field, optional. No PHI/audit/registry change. Keeps grounding
traceability (every anchor is still a source_id). Not flag-gated (inert unless a
grounded synthesis claim populates it). Descriptive-mode box: TICKABLE (no prompt change).

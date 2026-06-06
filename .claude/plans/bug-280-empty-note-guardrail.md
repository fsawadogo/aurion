# Plan — bug-280

## Task
#280 — Stage 1 delivers structurally-valid but EMPTY notes (zero populated required sections) as a silent "success". 7 of 16 recent dev notes were `completeness=0.00` — including sessions with 92/76/53 transcript segments — with no audit signal, no alarm, no UX.

## Why
The only input gate is the 20-char transcript guard (PR #244). Downstream, nothing flags "all required sections empty": the note is versioned, the session advances to `AWAITING_REVIEW`, `STAGE1_DELIVERED` is written, and the clinician sees an all-empty review screen presented as normal. `parse_note_response` silently backfills missing/out-of-template sections to `not_captured` (→ 0.00) with no log. `template_section_completeness` is a headline pilot metric — this gap hides exactly the failures it exists to measure.

## Approach
Make empty notes **visible** without failing the request (the note is real; the physician should see "nothing usable was captured" rather than a fake-complete note):
1. New audit event `STAGE1_EMPTY_NOTE` (enum + PHI-free field allowlist `{segment_count, transcript_char_count, completeness}`).
2. `transcription.py`: capture the `Note` `generate_stage1_note` returns; if `completeness_score <= 0.0`, write `STAGE1_EMPTY_NOTE` (counts + score only — never transcript text) before the `AWAITING_REVIEW` transition. Still delivers (no behavior change for the client).
3. `parse_note_response`: WARNING log when >0 template sections are backfilled (with out-of-template id count) and when 0 required sections end up populated — turns the silent 0.00 degradation into a greppable/alarmable signal.

## Acceptance criteria
- [ ] AC-1: `parse_note_response` with a model response whose section ids are all OUTSIDE the template → completeness `0.0`, every required section present as `not_captured` — `test_parse_empty_note.test_out_of_template_ids_yield_empty`.
- [ ] AC-2: empty `sections: []` → completeness `0.0` — `...test_no_sections_yields_empty`.
- [ ] AC-3: a populated required section → completeness `> 0.0` (guardrail does NOT misfire on a good note) — `...test_populated_required_is_nonzero`.
- [ ] AC-4: `STAGE1_EMPTY_NOTE` is in the audit field allowlist (so `write_audit` accepts the payload) — covered by the existing audit-allowlist coverage test + a direct assert.
- [ ] AC-5: backend tests green; `docker compose up` + `/health` 200.

## DRY / SOLID check
- **Existing helpers to reuse**: `write_audit` (+ its field-allowlist mechanism), `note.completeness_score` (already computed by `parse_note_response`), the note returned by `generate_stage1_note` (no re-read), the audit enum extension pattern.
- **New helper introduced?**: No. New enum member (OCP — audit events extend the enum) + a route-level guard reading an existing field.
- **OCP**: empty-note signal added via the audit enum, not a new branch in provider code.

## Out of scope (documented follow-ups)
- Configurable `pipeline.min_stage1_completeness` threshold (here we detect the unambiguous `completeness == 0` case; a soft threshold is an AppConfig follow-up).
- iOS "nothing captured — re-record?" UX keyed off the empty signal (iOS bundle).
- CloudWatch alarm on the `stage1_empty_note` rate (infra/Terraform follow-up — the event this PR adds is the prerequisite).
- Re-examining the historical 92/76/53-segment 0.00 sessions for the id-mismatch signature (investigation follow-up; the new WARNING log makes future ones self-report).
- `stop_reason`/truncation handling in the Anthropic provider (separate provider hardening).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_parse_empty_note.py -q` → green.
2. `cd backend && python3 -m pytest -q` → suite green (audit-allowlist coverage includes the new event).
3. `docker compose up -d && curl -fs localhost:8080/health` → 200.

## Security implications
PHI-safe by construction: the `STAGE1_EMPTY_NOTE` payload is integer counts + a float score — never transcript or claim text; the field allowlist enforces this at `write_audit`. The new WARNING logs carry stage/provider/template/ids counts only. No new secret/AI/consent path. Audit log stays append-only.

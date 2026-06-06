# Patient Identifier UI — close #161

## Task

#161 — Portal · patient identifier UI (read + write
`external_reference_id`). Close the remaining presentation gaps on top
of the encrypted-identifier infrastructure shipped in #152/#164/#194/#197.

## Why

Phase 9a added the KMS-encrypted `sessions.external_reference_id_encrypted`
column + the decryption helper. Subsequent PRs (#152, #164, #194, #197)
wired the read path through `GET /me/patients/{identifier}/sessions`,
the dashboard "Find by identifier" palette card, and the ⌘K command
palette token search. The `PATCH /sessions/{id}/identifier` write
endpoint and the `PatientIdentifierEditor` modal also exist today.

What is still **missing** to actually close #161:

1. The backend `PATCH /sessions/{id}/identifier` body has no format
   validation — it accepts a raw 9-digit SSN, an email, or a full
   name as a "patient identifier", which would route plain-PHI
   straight through the encryption helper into the audit story. AC-4
   in the issue scope is unmet.
2. `PatientIdentifierEditor` renders English strings via JSX
   literals — not via `useTranslations`. The other portal cards on
   the same screen all read from the `NoteReview.*` next-intl
   namespace after PR #257; this one slipped. FR-locale Québec users
   see a half-English modal.
3. There are no front-end tests for the editor — `PatientIdentifierEditor`
   is the load-bearing CRUD surface for a PHI field and has zero
   coverage today.

This satisfies CLAUDE.md §"Non-Negotiable Technical Rules — Privacy"
(PHI never in audit value), §"Voice enrollment" parallel (PHI is
encrypted at rest, never logged), and unblocks #57 (FHIR write-back
needs to trust the identifier shape) plus #61 (longitudinal context
needs the same identifier reproducible across sessions).

## Approach

**Single PR. Single lane (web). No new modules, no new endpoints, no
new tables.**

Backend (small surface):

- `backend/app/api/v1/sessions.py`:
  - Add a Pydantic `field_validator` on
    `ExternalReferenceIdRequest.external_reference_id` that rejects
    four explicit deny patterns with 422 (the API layer raises
    `ValueError`; FastAPI surfaces this as 422 unprocessable entity).
    Keep the patterns SIMPLE — four explicit checks, not regex soup:
      - `^\d{9}$` — raw US SSN
      - `^\d{3}-\d{2}-\d{4}$` — SSN with dashes
      - contains `@` — email
      - two-or-more whitespace-separated words — looks like a full name
      - length > 64 — `Field(max_length=64)`
  - Keep ALL the existing logic (encrypt, hash, audit) unchanged.

Tests:

- `backend/tests/unit/test_patient_identifier_format_gates.py` — new
  test module covering each deny pattern + the accept path (MRN
  shapes, free text, hyphen-id, etc.). Stays in the unit tier — no
  DB, no KMS, just Pydantic validation.

Web (presentation gaps):

- `web/components/portal/PatientIdentifierEditor.tsx`:
  - Swap every JSX literal to `useTranslations("NoteReview.identifier")`.
  - Add the same four deny gates client-side for fast feedback
    (single helper `validateIdentifier` defined once in the file).
    Hard cap at 64 chars on the `<input>` itself plus the validation
    text below.
  - Surface a localized error message above the input on validation
    fail; disable Save while invalid.

- `web/messages/en.json` + `web/messages/fr.json`:
  - Add a new `NoteReview.identifier` namespace covering the modal
    chrome (title, hint, placeholder, errors, save/clear/cancel, prior
    encounters, add-button label).
  - Keep keys consistent with how the rest of `NoteReview.*` is
    organized (flat where possible, one sub-namespace for
    `previousEncounters`).
  - Québec French per project memory.

Tests:

- `web/tests/PatientIdentifierEditor.spec.tsx` — new spec covering:
  - Renders "Add identifier" CTA when current is null.
  - Renders the chip + identifier value + edit icon when current is set.
  - Opens the modal on click; ESC closes; click-outside closes.
  - Format gates fire client-side (SSN / email / name / >64) and
    block Save.
  - Calls `setSessionExternalReferenceId(sessionId, value)` on save,
    invokes `onChange` with the API result.
  - Clear path passes `null` to the API.
  - EN + FR catalogs both contain the new `NoteReview.identifier.*`
    keys.

## Acceptance criteria

- [ ] AC-1: `PATCH /api/v1/sessions/{id}/identifier` with body
  `{"external_reference_id": "123456789"}` returns 422, no DB write.
  Verified by `pytest backend/tests/unit/test_patient_identifier_format_gates.py::test_rejects_raw_ssn -v`.
- [ ] AC-2: `PATCH /api/v1/sessions/{id}/identifier` with body
  `{"external_reference_id": "123-45-6789"}` returns 422.
  Verified by `…::test_rejects_dashed_ssn`.
- [ ] AC-3: `PATCH …/identifier` with body
  `{"external_reference_id": "patient@example.com"}` returns 422.
  Verified by `…::test_rejects_email`.
- [ ] AC-4: `PATCH …/identifier` with body
  `{"external_reference_id": "Jane Doe"}` returns 422.
  Verified by `…::test_rejects_full_name`.
- [ ] AC-5: `PATCH …/identifier` with body
  `{"external_reference_id": "a" * 65}` returns 422.
  Verified by `…::test_rejects_overlong`.
- [ ] AC-6: `PATCH …/identifier` with body
  `{"external_reference_id": "MRN-12345"}` succeeds (round-trips
  through the existing encrypt + audit + hash path, untouched).
  Verified by `…::test_accepts_canonical_mrn` AND the existing
  `test_session_identifier.py` suite still passes.
- [ ] AC-7: The audit row written on a successful set contains
  `{cleared: false, actor_id: <uuid>}` and nothing else — no
  identifier value. Verified by the existing
  `test_external_reference_id_set_audit_carries_no_identifier_value`
  (regression guard preserved).
- [ ] AC-8: PHI logging guard — `grep -RnE
  '(logger|logging|print).*(external_reference_id|patient_identifier|identifier_value)'
  backend/app` returns ONLY the existing "Failed to decrypt …
  session=%s" line (which logs the session id, not the value). No
  new lines.
- [ ] AC-9: `PatientIdentifierEditor` renders entirely from the
  `NoteReview.identifier` namespace in both EN and FR. Verified by
  `vitest web/tests/PatientIdentifierEditor.spec.tsx -t 'localizes'`.
- [ ] AC-10: Client-side format gates block Save and surface a
  localized error matching the backend rules. Verified by the same
  spec file's "gates" describe block.
- [ ] AC-11: `web/messages/en.json` and `web/messages/fr.json` are
  structurally identical under the new namespace (same key tree).
  Verified by the spec's "i18n parity" test.

## DRY / SOLID check

- **Existing helpers to reuse**:
  - `setSessionExternalReferenceId` (web/lib/portal-api.ts:223) —
    already wraps the PATCH; the editor calls it untouched.
  - `listMySessionsByPatientIdentifier` (web/lib/portal-api.ts:237) —
    used for the prior-encounters list inside the modal; no change.
  - `useTranslations("NoteReview")` + sub-namespace pattern from
    PR #257 — apply identically.
  - `withIntl` test helper at `web/tests/helpers/intl.tsx` — wraps
    components for `useTranslations` in tests.
  - `encrypt_str` / `decrypt_str` / `hash_identifier` — unchanged on
    the backend; we only insert a validator above them.
- **New helper introduced?**: One — `validateIdentifier` as a pure
  function inside `PatientIdentifierEditor.tsx` (returns
  `{ ok: true } | { ok: false; reason: "ssn" | "email" | "name" |
  "tooLong" }`). It is the iOS / portal client-side equivalent of
  the backend `field_validator`. Could in principle be lifted to
  `web/lib/identifier-validation.ts` if a third call site appears
  (iOS PostEncounter, AUR-IDENT-179 — currently a separate iOS PR);
  for now both call sites we have stay in their own file (backend
  in Pydantic, web in the editor).

## Out of scope

- iOS `PostEncounter` identifier UI — covered by a separate iOS PR
  per the issue.
- `/portal/patients` index page (list of unique identifiers + session
  counts) — explicitly deferred in the issue's status comment to a
  follow-up.
- `/portal/patients/[identifier]` chronology page — same comment.
- Soft-merge UX for two identifiers that turn out to be the same
  patient — same comment.
- Surfacing the identifier on `notes/page.tsx` inbox (already done in
  PR #194 via the unified search box and identifier-as-chip in the
  list row).
- Any change to the column / migration / hash / encryption logic.
- Any change to `EXTERNAL_REFERENCE_ID_SET` audit event surface.

## Test plan (executable)

```
# Backend — new format-gates module
cd backend && python3 -m pytest tests/unit/test_patient_identifier_format_gates.py -v

# Backend — regression: existing identifier suite still passes
cd backend && python3 -m pytest tests/unit/test_session_identifier.py tests/unit/test_audit_events.py -v

# Backend — PHI grep audit (AC-8)
grep -RnE '(logger|logging|print).*(external_reference_id|patient_identifier|identifier_value)' backend/app
# Should print only the existing "Failed to decrypt external_reference_id for session=%s" line.

# Web — new editor spec
cd web && npx vitest run tests/PatientIdentifierEditor.spec.tsx

# Web — full suite (regression)
cd web && npx vitest run

# Web — typecheck
cd web && npx tsc --noEmit

# Web — i18n key parity
node -e "const en=require('./web/messages/en.json'); const fr=require('./web/messages/fr.json'); const walk=(o,p='')=>Object.entries(o).flatMap(([k,v])=>typeof v==='object'?walk(v,p+k+'.'):[p+k]); const ek=new Set(walk(en.NoteReview.identifier)); const fk=new Set(walk(fr.NoteReview.identifier)); if(ek.size!==fk.size||[...ek].some(k=>!fk.has(k)))throw new Error('NoteReview.identifier keys diverge');"
```

## Security implications

- **PHI touched**: yes — `external_reference_id` is PHI. Encrypted
  at rest via KMS, decrypted only for the row owner in the API
  response, never logged at any tier. This PR adds a validator
  ABOVE the existing encrypt path; nothing changes about how the
  encrypted bytes flow.
- **Audit log**: unchanged. The `EXTERNAL_REFERENCE_ID_SET` event
  still carries only `{actor_id, cleared}`; no path adds the
  identifier value to the audit row. Regression-locked by the
  existing test.
- **Logs**: the format-gate `ValueError` carries a short reason
  string (`"identifier looks like SSN"`, etc.) but NEVER the
  rejected value. Verified by the AC-8 grep gate.
- **AI prompts**: not touched.
- **Consent gate**: not touched.
- **Secrets**: not touched.
- **Fail-closed**: the validator rejects on match — a bypass would
  require Pydantic to silently accept an invalid value, which is
  not how `field_validator` is wired.
